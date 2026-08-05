"""Audiobook Production API — durable, multi-tenant.

Foundation phase changes vs the prototype:
  * No in-memory ``active_tasks`` — everything is a durable row in Postgres.
  * No daemon threads — synthesis runs are enqueued as jobs and executed by a
    separate, restart-safe worker process (see worker.py).
  * Authenticated, org-scoped access: a task/job id no longer authorizes access;
    the caller must be a member of the owning organization.
"""
import os
import uuid

from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, request, send_file
from flask_cors import CORS

from auth import (
    AuthError,
    current_identity,
    login as auth_login,
    require_auth,
    resolve_org,
    signup as auth_signup,
)
from auth.guard import AuthzError
from db import init_engine, get_session
from db.models import ChapterResult, Job, JobStatus, Project
from jobs import queue as q
from billing import QuotaExceeded, month_usage, quota_for, remaining_quota
from billing.usage import check_quota
from ratelimit import check_rate_limit
from services.providers import ProviderRegistry
from services.synthesis_cache import SynthesisCache
from services.text_processor import TextProcessor
from services.file_manager import FileManager
from storage import get_storage

from observability import configure_logging, init_sentry, new_request_id, request_id_var
from webhooks import github_bp
from voice_city import voice_city_bp
from services.voice_city.production import (
    VoiceProductionError, attach_voice_snapshot, load_voice_snapshot,
    resolve_voice_version_for_request,
)

load_dotenv()
configure_logging()
init_sentry()
init_engine()

# Signed download links expire after this many seconds.
SIGNED_URL_TTL = int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))
# Rate limit for job creation, per organization.
SYNTHESIZE_RATE_LIMIT = int(os.getenv("SYNTHESIZE_RATE_LIMIT", "30"))
SYNTHESIZE_RATE_WINDOW = int(os.getenv("SYNTHESIZE_RATE_WINDOW_SECONDS", "60"))

app = Flask(__name__)
app.register_blueprint(github_bp)
app.register_blueprint(voice_city_bp)

# Scoped CORS (blueprint rescue item), defaults to the local dev origin.
allow_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").strip()
if allow_origins == "*":
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
else:
    origins = [o.strip() for o in allow_origins.split(",") if o.strip()] or ["http://localhost:5173"]
    CORS(app, resources={r"/api/*": {"origins": origins}}, supports_credentials=True)

app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".pdf", ".docx"}
ALLOWED_UPLOAD_MIMETYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

registry = ProviderRegistry()
text_processor = TextProcessor()
file_manager = FileManager(UPLOAD_FOLDER)
cache = SynthesisCache(os.getenv("CACHE_FOLDER", "cache"))


# --------------------------------------------------------------------------- #
# Request-scoped DB session
# --------------------------------------------------------------------------- #
@app.before_request
def _open_session():
    # Correlation id: reuse an inbound X-Request-Id (from a proxy) or mint one.
    rid = request.headers.get("X-Request-Id") or new_request_id()
    g.request_id = rid
    request_id_var.set(rid)
    g.db = get_session()


@app.after_request
def _tag_response(resp):
    rid = g.get("request_id")
    if rid:
        resp.headers["X-Request-Id"] = rid
    return resp


@app.teardown_request
def _close_session(exc):
    session = g.pop("db", None)
    if session is not None:
        if exc is not None:
            session.rollback()
        session.close()


@app.errorhandler(AuthzError)
def _authz(e):
    return jsonify({"error": str(e)}), 403


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #
def _chapter_json(c: ChapterResult) -> dict:
    return {
        "index": c.index,
        "title": c.title,
        "status": c.status.value,
        "cached_chunks": c.cached_chunks,
        "total_chunks": c.total_chunks,
        "qc": None if c.qc_passed is None else {
            "duration_s": c.duration_s,
            "loudness_dbfs": c.loudness_dbfs,
            "peak_dbfs": c.peak_dbfs,
            "silence_ratio": c.silence_ratio,
            "clipping": c.clipping,
            "issues": (c.qc_issues or "").split("\n") if c.qc_issues else [],
            "passed": c.qc_passed,
        },
    }


def _job_json(job: Job) -> dict:
    snapshot = load_voice_snapshot(g.db, job.id)
    formats = [f for f in ("mp3" if job.output_mp3_key else "", "m4b" if job.output_m4b_key else "") if f]
    qc_issues = [
        {"chapter": c.title, "issues": (c.qc_issues or "").split("\n")}
        for c in job.chapters if c.qc_issues
    ]
    return {
        "task_id": job.id,
        "job_id": job.id,
        "project_id": job.project_id,
        "status": job.status.value,
        "progress": job.progress,
        "provider": job.provider,
        "voice_version_id": snapshot.voice_version_id if snapshot else None,
        "voice_display_name": (snapshot.provenance or {}).get("voice_name") if snapshot else None,
        "voice_parameter_fingerprint": snapshot.fingerprint if snapshot else None,
        "chapters_count": job.chapters_count,
        "current_chapter": job.current_chapter,
        "chapters": [_chapter_json(c) for c in job.chapters],
        "cached_chunks": job.cached_chunks,
        "synthesized_chunks": job.synthesized_chunks,
        "formats": formats,
        "qc_issues": qc_issues,
        "attempts": job.attempts,
        "error": job.error,
    }


def _get_owned_job(job_id: str) -> Job:
    """Load a job and assert the caller's org owns it (403 otherwise)."""
    identity = current_identity()
    job = g.db.get(Job, job_id)
    if not job:
        raise AuthzError("Job not found")  # 403, not 404: don't reveal existence
    resolve_org(g.db, identity, job.organization_id)
    return job


# --------------------------------------------------------------------------- #
# Auth endpoints
# --------------------------------------------------------------------------- #
@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.json or {}
    try:
        user, org, token = auth_signup(
            g.db, data.get("email"), data.get("password"),
            display_name=data.get("display_name"), org_name=data.get("org_name"),
        )
        g.db.commit()
    except AuthError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "token": token,
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "organization": {"id": org.id, "name": org.name},
    })


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    try:
        user, token = auth_login(g.db, data.get("email"), data.get("password"))
    except AuthError as e:
        return jsonify({"error": str(e)}), 401
    return jsonify({"token": token, "user": {"id": user.id, "email": user.email}})


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    ident = current_identity()
    return jsonify({
        "user": {"id": ident.user.id, "email": ident.user.email, "display_name": ident.user.display_name},
        "organization": {"id": ident.org.id, "name": ident.org.name},
        "role": ident.role,
    })


# --------------------------------------------------------------------------- #
# Provider / voice discovery (public)
# --------------------------------------------------------------------------- #
@app.route("/api/providers", methods=["GET"])
def get_providers():
    return jsonify(registry.describe_all())


@app.route("/api/voices", methods=["GET"])
def get_voices():
    provider_name = request.args.get("provider") or registry.default().name
    provider = registry.get(provider_name)
    if not provider:
        return jsonify({"error": f"Unknown provider '{provider_name}'"}), 400
    return jsonify(provider.list_voices(request.args.get("language")))


# --------------------------------------------------------------------------- #
# Upload / text extraction (authenticated)
# --------------------------------------------------------------------------- #
@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type '{ext or 'unknown'}'. "
                                 f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"}), 415
    if file.mimetype and file.mimetype not in ALLOWED_UPLOAD_MIMETYPES:
        return jsonify({"error": f"Unsupported content type '{file.mimetype}'"}), 415

    file_path = file_manager.save_uploaded_file(file)
    if not file_path:
        return jsonify({"error": "Failed to save file"}), 500
    try:
        text_content = file_manager.read_text_file(file_path)
    finally:
        file_manager.cleanup_file(file_path)

    chapters = text_processor.split_by_chapters(text_content)
    return jsonify({
        "text": text_content,
        "characters_count": len(text_content),
        "words_count": len(text_content.split()),
        "detected_chapters": [c["title"] for c in chapters],
    })


# --------------------------------------------------------------------------- #
# Projects + jobs (authenticated, org-scoped)
# --------------------------------------------------------------------------- #
@app.route("/api/synthesize", methods=["POST"])
@require_auth
def synthesize():
    """Create a project (if needed) and enqueue a durable production job."""
    identity = current_identity()
    data = request.json or {}
    text = data.get("text")
    if not text or not text.strip():
        return jsonify({"error": "No text provided"}), 400

    voice_version_id = data.get("voice_version_id")
    authoritative_voice_id = None
    if voice_version_id:
        try:
            provider_name, authoritative_voice_id = resolve_voice_version_for_request(
                g.db, organization_id=identity.org.id, voice_version_id=str(voice_version_id)
            )
        except VoiceProductionError as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        provider_name = data.get("provider") or registry.default().name

    if provider_name == "voice-city" and not voice_version_id:
        return jsonify({"error": "Voice City production requires an immutable voice_version_id"}), 400

    provider = registry.get(provider_name)
    if not provider:
        return jsonify({"error": f"Unknown provider '{provider_name}'"}), 400
    if not provider.is_available():
        return jsonify({"error": f"Provider '{provider_name}' is not configured/available"}), 400

    voice_id = authoritative_voice_id or data.get("voice_id")
    if not voice_id:
        voices = provider.list_voices("en")
        voice_id = voices[0]["id"] if voices else None
    if not voice_id:
        return jsonify({"error": "No voice available for this provider"}), 400

    formats = data.get("formats") or ["mp3", "m4b"]

    # Rate limit: cap how many jobs an org can create per window.
    rl = check_rate_limit(
        g.db, f"synthesize:{identity.org.id}",
        limit=SYNTHESIZE_RATE_LIMIT, window_seconds=SYNTHESIZE_RATE_WINDOW,
    )
    g.db.commit()  # persist the counter increment regardless of outcome
    if not rl.allowed:
        resp = jsonify({"error": "Rate limit exceeded. Please slow down.",
                        "retry_after": rl.retry_after})
        resp.headers["Retry-After"] = str(rl.retry_after)
        return resp, 429

    # Quota: reject up-front if this run would exceed the org's monthly quota.
    # (Free providers never count against quota.)
    try:
        check_quota(g.db, identity.org, requested_chars=len(text), paid=provider.paid)
    except QuotaExceeded as e:
        return jsonify({
            "error": "Monthly usage quota exceeded",
            "used": e.used, "quota": e.quota, "requested": e.requested,
        }), 402  # Payment Required

    project = Project(
        organization_id=identity.org.id,
        created_by=identity.user.id,
        title=data.get("title") or "Untitled",
        author=data.get("author") or None,
        source_text=text,
    )
    g.db.add(project)
    g.db.flush()

    job = Job(
        organization_id=identity.org.id,
        project_id=project.id,
        created_by=identity.user.id,
        provider=provider_name,
        voice_id=voice_id,
        engine=data.get("engine", "neural"),
        formats=",".join(formats),
    )
    q.enqueue_job(g.db, job)
    if voice_version_id:
        try:
            attach_voice_snapshot(
                g.db, job=job, organization_id=identity.org.id,
                voice_version_id=str(voice_version_id),
                performance_overrides=data.get("voice_overrides") or {},
                direction_plan=data.get("voice_direction") or {},
                actor_user_id=identity.user.id,
            )
        except VoiceProductionError as exc:
            g.db.rollback()
            return jsonify({"error": str(exc)}), 400
    g.db.commit()

    return jsonify({"task_id": job.id, "job_id": job.id, "status": job.status.value})


@app.route("/api/task/<job_id>", methods=["GET"])
@app.route("/api/jobs/<job_id>", methods=["GET"])
@require_auth
def get_job(job_id):
    job = _get_owned_job(job_id)
    return jsonify(_job_json(job))


@app.route("/api/jobs", methods=["GET"])
@require_auth
def list_jobs():
    identity = current_identity()
    jobs = (
        g.db.query(Job)
        .filter(Job.organization_id == identity.org.id)
        .order_by(Job.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify([_job_json(j) for j in jobs])


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
@require_auth
def cancel_job(job_id):
    job = _get_owned_job(job_id)
    if job.is_terminal:
        return jsonify({"error": f"Job already {job.status.value}"}), 409
    q.request_cancel(g.db, job)
    g.db.commit()
    return jsonify({"job_id": job.id, "status": job.status.value, "cancel_requested": True})


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
@require_auth
def delete_job(job_id):
    """Delete a job and its stored audio assets (org-scoped)."""
    from jobs.retention import delete_job_assets

    job = _get_owned_job(job_id)
    removed = delete_job_assets(g.db, job)
    g.db.delete(job)
    g.db.commit()
    return jsonify({"job_id": job_id, "deleted": True, "assets_removed": removed})


@app.route("/api/jobs/<job_id>/approve", methods=["POST"])
@require_auth
def approve_job(job_id):
    """Approve a job that the QC gate held for review (needs_review -> succeeded)."""
    job = _get_owned_job(job_id)
    try:
        q.approve_reviewed_job(g.db, job)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    g.db.commit()
    return jsonify({"job_id": job.id, "status": job.status.value})


@app.route("/api/jobs/<job_id>/reject", methods=["POST"])
@require_auth
def reject_job(job_id):
    """Reject a reviewed job (needs_review -> failed)."""
    job = _get_owned_job(job_id)
    reason = (request.json or {}).get("reason", "")
    try:
        q.reject_reviewed_job(g.db, job, reason)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    g.db.commit()
    return jsonify({"job_id": job.id, "status": job.status.value})


@app.route("/api/download/<job_id>", methods=["GET"])
@app.route("/api/jobs/<job_id>/download", methods=["GET"])
@require_auth
def download(job_id):
    """Issue a time-limited signed URL for the requested output.

    We no longer stream bytes through this business endpoint; the client (or the
    browser via ?redirect=1) fetches directly from storage with an expiring link.
    Jobs held for review are downloadable so a reviewer can listen before deciding.
    """
    job = _get_owned_job(job_id)
    if job.status not in (JobStatus.succeeded, JobStatus.needs_review):
        return jsonify({"error": "Audiobook not ready"}), 409

    fmt = request.args.get("format", "mp3")
    key = job.output_mp3_key if fmt == "mp3" else job.output_m4b_key
    if not key:
        return jsonify({"error": f"No {fmt} output available"}), 404

    storage = get_storage()
    if not storage.exists(key):
        return jsonify({"error": f"No {fmt} output available"}), 404

    download_name = f"audiobook_{job_id}.{fmt}"
    signed = storage.signed_url(key, expires_in=SIGNED_URL_TTL, download_name=download_name)
    if request.args.get("redirect") == "1":
        return redirect(signed.url, code=302)
    return jsonify({"url": signed.url, "expires_in": signed.expires_in})


@app.route("/api/files/<path:key>", methods=["GET"])
def serve_local_file(key):
    """Serve a local-storage object for a valid signed URL.

    Only used by the LocalStorage backend (cloud backends sign URLs that point
    straight at the object store). Authorization is the HMAC token + expiry, so
    this route is deliberately unauthenticated — the signature IS the grant.
    """
    from storage.local import LocalStorage

    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        return jsonify({"error": "Not found"}), 404

    try:
        expires = int(request.args.get("expires", "0"))
    except ValueError:
        return jsonify({"error": "Invalid token"}), 400
    sig = request.args.get("sig", "")
    if not storage.verify(key, expires, sig):
        return jsonify({"error": "Invalid or expired link"}), 403
    if not storage.exists(key):
        return jsonify({"error": "Not found"}), 404

    mimetype = "audio/mpeg" if key.endswith(".mp3") else "audio/mp4" if key.endswith(".m4b") else "application/octet-stream"
    download_name = request.args.get("name") or os.path.basename(key)
    return send_file(storage._path(key), as_attachment=True, download_name=download_name, mimetype=mimetype)


@app.route("/api/usage", methods=["GET"])
@require_auth
def usage():
    """This org's current-month usage and remaining quota (cost ledger view)."""
    identity = current_identity()
    mu = month_usage(g.db, identity.org.id)
    quota = quota_for(identity.org)
    return jsonify({
        "period": mu["period"],
        "characters": mu["characters"],
        "cost_usd": mu["cost_usd"],
        "quota": quota or None,  # None = unlimited
        "remaining": remaining_quota(g.db, identity.org),
    })


# --------------------------------------------------------------------------- #
# Ops
# --------------------------------------------------------------------------- #
@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    return jsonify(cache.stats())


@app.route("/api/health", methods=["GET"])
def health_check():
    db_ok = True
    try:
        from sqlalchemy import text
        g.db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "service": "Audiobook Production API",
        "database": "ok" if db_ok else "unreachable",
        "providers": registry.describe_all(),
    }), (200 if db_ok else 503)


# --------------------------------------------------------------------------- #
# EPUB Generation (authenticated, org-scoped)
# --------------------------------------------------------------------------- #
@app.route("/api/export/epub", methods=["POST"])
@require_auth
def generate_epub():
    """Generate EPUB from project chapters.
    
    Request body:
    {
        "title": "Book Title",
        "author": "Author Name",
        "chapters": [
            {"title": "Chapter 1", "content": "..."},
            ...
        ]
    }
    """
    from services.epub_generator import EPUBGenerator
    identity = current_identity()
    data = request.json or {}
    
    title = data.get("title", "Untitled")
    author = data.get("author", "Unknown")
    chapters = data.get("chapters", [])
    
    if not chapters:
        return jsonify({"error": "No chapters provided"}), 400
    
    try:
        generator = EPUBGenerator.from_chapters_list(title, author, chapters)
        epub_bytes = generator.to_bytes()
        
        # Optionally store in object storage
        storage_key = f"epub/{identity.org.id}/{uuid.uuid4().hex}.epub"
        storage = get_storage()
        storage.put_bytes(storage_key, epub_bytes)
        
        return jsonify({
            "success": True,
            "size": len(epub_bytes),
            "storage_key": storage_key,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jobs/<job_id>/export/epub", methods=["GET"])
@require_auth
def export_job_as_epub(job_id):
    """Export a completed synthesis job as EPUB.
    
    Uses the job's chapters data to generate an EPUB file.
    """
    from services.epub_generator import EPUBGenerator
    
    job = _get_owned_job(job_id)
    if job.status != JobStatus.succeeded:
        return jsonify({"error": "Job must be succeeded to export"}), 409
    
    if not job.project or not job.project.title:
        return jsonify({"error": "Missing project metadata"}), 400
    
    try:
        # Load chapters from job results
        chapters_data = []
        for result in job.chapter_results:
            if result.chapter_title:
                chapters_data.append({
                    "title": result.chapter_title,
                    "content": result.text_content or ""
                })
        
        if not chapters_data:
            return jsonify({"error": "No chapter content available"}), 404
        
        # Generate EPUB
        generator = EPUBGenerator.from_chapters_list(
            job.project.title,
            job.project.author or "Unknown",
            chapters_data
        )
        epub_bytes = generator.to_bytes()
        
        # Optionally store in object storage
        storage_key = f"epub/{job.organization_id}/{job_id}.epub"
        storage = get_storage()
        storage.put_bytes(storage_key, epub_bytes)
        
        download_name = f"{job.project.title.replace(' ', '_')}.epub"
        signed = storage.signed_url(storage_key, expires_in=SIGNED_URL_TTL, download_name=download_name)
        
        if request.args.get("redirect") == "1":
            return redirect(signed.url, code=302)
        
        return jsonify({
            "success": True,
            "url": signed.url,
            "expires_in": signed.expires_in,
            "size": len(epub_bytes),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", "5000"))
    except ValueError:
        import sys
        print("Error: PORT must be a valid integer", file=sys.stderr)
        sys.exit(1)
    debug = os.getenv("FLASK_ENV") == "development"
    app.run(debug=debug, host=host, port=port)

