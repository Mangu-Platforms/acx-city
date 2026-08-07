"""acxcity_mcp — MCP server exposing the audiobook platform to AI agents.

Operator tools over the existing system of record. Runs as its own process
(like worker.py), speaking streamable HTTP so remote MCP clients (Claude,
Cursor, etc.) can connect over the network.

Read tools (health, jobs, orgs, usage, pipeline status) are always
available. Write tools (cancel/approve/reject/enqueue) reuse the same queue
primitives as the REST API and are additionally gated by MCP_WRITE_ENABLED —
with it unset they are listed but every call returns an error, so a leaked
key on a read-only deployment still cannot mutate jobs.

Gating (both required, per the MANGU MCN baseline):
    MCP_ENABLED=true   — refuses to start otherwise
    MCP_API_KEY=...    — clients must send "Authorization: Bearer <key>"

Optional:
    MCP_WRITE_ENABLED=true — allow the write tools (default: read-only)
    MCP_HOST (default 0.0.0.0), MCP_PORT (default 8765; Railway injects PORT)

Run: python mcp_server.py
"""
from __future__ import annotations

import hmac
import os
import sys
import uuid as _uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import func, select, text

# Own entry point: load backend/.env before any env reads below (MCP_HOST,
# PORT, MCP_ENABLED, MCP_API_KEY), same as app.py does for the API.
load_dotenv(Path(__file__).resolve().parent / ".env")

from billing.usage import month_usage, quota_for  # noqa: E402
from db.models import Job, JobStatus, Organization, Project  # noqa: E402
from db.session import session_scope  # noqa: E402
from jobs.queue import approve_reviewed_job, reject_reviewed_job, request_cancel  # noqa: E402
from observability.logging_setup import configure_logging  # noqa: E402
from services.providers.registry import ProviderRegistry  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

registry = ProviderRegistry()

mcp = FastMCP(
    "acxcity_mcp",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", os.getenv("MCP_PORT", "8765"))),
    stateless_http=True,
)


def _valid_uuid(value: str) -> bool:
    """GUID columns are native uuid on Postgres; reject bad input up front so
    lookups return a friendly error instead of a database DataError."""
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _job_dict(job: Job, chapters: bool = False) -> dict:
    d = {
        "job_id": job.id,
        "project_id": job.project_id,
        "organization_id": job.organization_id,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "progress": job.progress,
        "provider": job.provider,
        "voice_id": job.voice_id,
        "chapters_count": job.chapters_count,
        "current_chapter": job.current_chapter,
        "attempts": job.attempts,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
    if chapters:
        d["chapters"] = [
            {
                "index": c.index,
                "title": c.title,
                "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                "qc_passed": c.qc_passed,
                "qc_issues": c.qc_issues,
            }
            for c in sorted(job.chapters, key=lambda c: c.index)
        ]
    return d


@mcp.tool(annotations={"readOnlyHint": True})
def acx_health() -> dict:
    """Check platform health: database reachability and available TTS providers.

    Returns status ("healthy"/"degraded"), database state, and the provider list
    with availability and whether each is paid.
    """
    db_ok = True
    try:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
        "providers": registry.describe_all(),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def acx_list_jobs(
    status: Optional[str] = None,
    organization_id: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """List synthesis jobs, newest first.

    Args:
        status: filter by job status — one of queued, running, succeeded,
            needs_review, failed, canceled. Omit for all.
        organization_id: filter to one organization. Omit for all orgs.
        limit: max rows (1-100, default 20).
    """
    limit = max(1, min(int(limit), 100))
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        try:
            stmt = stmt.where(Job.status == JobStatus(status))
        except ValueError:
            valid = ", ".join(s.value for s in JobStatus)
            return {"error": f"Unknown status '{status}'. Valid: {valid}"}
    if organization_id:
        if not _valid_uuid(organization_id):
            return {"error": f"'{organization_id}' is not a valid organization UUID. "
                             "Use acx_list_organizations to browse ids."}
        stmt = stmt.where(Job.organization_id == organization_id)
    with session_scope() as s:
        jobs = s.execute(stmt).scalars().all()
        return {"count": len(jobs), "jobs": [_job_dict(j) for j in jobs]}


@mcp.tool(annotations={"readOnlyHint": True})
def acx_get_job(job_id: str) -> dict:
    """Get one job with full detail including per-chapter status and QC results.

    Args:
        job_id: the job UUID (from acx_list_jobs).
    """
    if not _valid_uuid(job_id):
        return {"error": f"'{job_id}' is not a valid job UUID. Use acx_list_jobs to browse ids."}
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return {"error": f"Job '{job_id}' not found. Use acx_list_jobs to browse ids."}
        return _job_dict(job, chapters=True)


@mcp.tool(annotations={"readOnlyHint": True})
def acx_list_organizations(limit: int = 50) -> dict:
    """List organizations with job counts, for scoping other tool calls.

    Args:
        limit: max rows (1-200, default 50).
    """
    limit = max(1, min(int(limit), 200))
    with session_scope() as s:
        rows = s.execute(
            select(Organization, func.count(Job.id))
            .outerjoin(Job, Job.organization_id == Organization.id)
            .group_by(Organization.id)
            .order_by(Organization.created_at)
            .limit(limit)
        ).all()
        return {
            "count": len(rows),
            "organizations": [
                {"id": o.id, "name": o.name, "jobs": int(n),
                 "monthly_char_quota": o.monthly_char_quota}
                for o, n in rows
            ],
        }


@mcp.tool(annotations={"readOnlyHint": True})
def acx_usage(organization_id: str, period: Optional[str] = None) -> dict:
    """Get an organization's synthesis usage and quota for a month.

    Args:
        organization_id: org UUID (from acx_list_organizations).
        period: month as YYYY-MM. Omit for the current month.
    """
    if not _valid_uuid(organization_id):
        return {"error": f"'{organization_id}' is not a valid organization UUID. "
                         "Use acx_list_organizations to browse ids."}
    with session_scope() as s:
        org = s.get(Organization, organization_id)
        if org is None:
            return {"error": f"Organization '{organization_id}' not found. "
                             "Use acx_list_organizations to browse ids."}
        usage = month_usage(s, org.id, period)
        quota = quota_for(org)
        usage["quota"] = quota or None
        usage["remaining"] = max(quota - usage["characters"], 0) if quota else None
        return usage


_WRITES_DISABLED_ERROR = (
    "Write tools are disabled on this deployment. "
    "Set MCP_WRITE_ENABLED=true on the MCP service to allow cancel/approve/reject."
)


def _writes_enabled() -> bool:
    return os.getenv("MCP_WRITE_ENABLED", "").lower() == "true"


def _load_job(session, job_id: str) -> tuple[Optional[Job], Optional[dict]]:
    """Fetch a job for a write tool, or an error dict explaining what's wrong."""
    if not _writes_enabled():
        return None, {"error": _WRITES_DISABLED_ERROR}
    if not _valid_uuid(job_id):
        return None, {"error": f"'{job_id}' is not a valid job UUID. "
                               "Use acx_list_jobs to browse ids."}
    job = session.get(Job, job_id)
    if job is None:
        return None, {"error": f"Job '{job_id}' not found. Use acx_list_jobs to browse ids."}
    return job, None


@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
def acx_cancel_job(job_id: str) -> dict:
    """Cancel a job. Queued jobs are canceled immediately; running jobs stop
    cooperatively at their next heartbeat (status stays "running" with
    cancel_requested set until the worker notices).

    Requires MCP_WRITE_ENABLED=true on the server. Terminal jobs (succeeded,
    needs_review, failed, canceled) cannot be canceled.

    Args:
        job_id: the job UUID (from acx_list_jobs).
    """
    with session_scope() as s:
        job, err = _load_job(s, job_id)
        if err:
            return err
        if job.is_terminal:
            return {"error": f"Job already {job.status.value}; nothing to cancel."}
        request_cancel(s, job)
        return {"job_id": job.id, "status": job.status.value, "cancel_requested": True}


@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
def acx_approve_job(job_id: str) -> dict:
    """Approve a QC-held job, promoting needs_review -> succeeded.

    Requires MCP_WRITE_ENABLED=true on the server. Only jobs in needs_review
    (held by the QC gate) can be approved; use acx_get_job to inspect the
    per-chapter QC issues first.

    Args:
        job_id: the job UUID (from acx_list_jobs, status needs_review).
    """
    with session_scope() as s:
        job, err = _load_job(s, job_id)
        if err:
            return err
        try:
            approve_reviewed_job(s, job)
        except ValueError as e:
            return {"error": str(e)}
        return {"job_id": job.id, "status": job.status.value}


@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
def acx_reject_job(job_id: str, reason: Optional[str] = None) -> dict:
    """Reject a QC-held job, marking needs_review -> failed.

    Requires MCP_WRITE_ENABLED=true on the server. Only jobs in needs_review
    (held by the QC gate) can be rejected; use acx_get_job to inspect the
    per-chapter QC issues first.

    Args:
        job_id: the job UUID (from acx_list_jobs, status needs_review).
        reason: optional human-readable reason, recorded on the job.
    """
    with session_scope() as s:
        job, err = _load_job(s, job_id)
        if err:
            return err
        try:
            reject_reviewed_job(s, job, reason or "")
        except ValueError as e:
            return {"error": str(e)}
        return {"job_id": job.id, "status": job.status.value, "reason_recorded": job.error}


def _require_auth_middleware(app):
    """Wrap the ASGI app: every request must bear the MCP_API_KEY."""
    expected = os.environ["MCP_API_KEY"]

    async def middleware(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = (headers.get(b"authorization") or b"").decode()
            token = auth[7:] if auth.lower().startswith("bearer ") else ""
            if not (token and hmac.compare_digest(token, expected)):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": b'{"error": "unauthorized: missing or bad bearer token"}'})
                return
        await app(scope, receive, send)

    return middleware


# --------------------------------------------------------------------------- #
# VoxEngine write tools (Phase 5+)
# --------------------------------------------------------------------------- #
# Note: cancel/approve/reject are defined above with the MCP_WRITE_ENABLED
# gate and cooperative-cancel semantics (request_cancel leaves running jobs
# to stop at their next heartbeat instead of yanking status out from under
# the worker). The Phase 5 duplicates were dropped in favor of those.

@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": False})
def acx_enqueue_synthesis(
    project_id: str,
    provider: str = "edge",
    voice_id: str = "en-US-AriaNeural",
    formats: str = "mp3,m4b",
) -> dict:
    """Enqueue a new synthesis job for a project.

    Requires MCP_WRITE_ENABLED=true on the server — enqueueing creates
    billable synthesis work. Each call creates a new job (not idempotent).

    Args:
        project_id: the project UUID.
        provider: TTS provider (edge, polly, kokoro, fish_speech).
        voice_id: voice identifier for the provider.
        formats: comma-separated output formats (mp3, m4b, wav).
    """
    if not _writes_enabled():
        return {"error": _WRITES_DISABLED_ERROR}
    if not _valid_uuid(project_id):
        return {"error": f"'{project_id}' is not a valid project UUID."}
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project is None:
            return {"error": f"Project '{project_id}' not found."}
        if not project.source_text or not project.source_text.strip():
            return {"error": "Project has no source text to synthesize."}

        job = Job(
            organization_id=project.organization_id,
            project_id=project.id,
            provider=provider,
            voice_id=voice_id,
            formats=formats,
            status=JobStatus.queued,
        )
        s.add(job)
        s.flush()
        return {
            "job_id": job.id,
            "status": "queued",
            "provider": provider,
            "voice_id": voice_id,
            "message": "Synthesis job enqueued.",
        }


@mcp.tool(annotations={"readOnlyHint": True})
def acx_get_pipeline_status(project_id: str) -> dict:
    """Get multi-agent pipeline status for a project.

    Args:
        project_id: the project UUID.
    """
    if not _valid_uuid(project_id):
        return {"error": f"'{project_id}' is not a valid project UUID."}

    from db.voxengine_models import PipelineTrace

    with session_scope() as s:
        project = s.get(Project, project_id)
        if project is None:
            return {"error": f"Project '{project_id}' not found."}

        job = s.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not job:
            return {"error": "No job found for this project."}

        traces = s.execute(
            select(PipelineTrace)
            .where(PipelineTrace.job_id == job.id)
            .order_by(PipelineTrace.chapter_number)
        ).scalars().all()

        completed = sum(1 for t in traces if t.status == "completed")
        failed = sum(1 for t in traces if t.status == "failed")
        total_cost = sum(
            float(t.agent2_cost_usd or 0) + float(t.agent3_cost_usd or 0) +
            float(t.agent4_cost_usd or 0) + float(t.agent5_cost_usd or 0)
            for t in traces
        )

        return {
            "job_id": job.id,
            "project_id": project_id,
            "chapters_total": len(traces),
            "chapters_completed": completed,
            "chapters_failed": failed,
            "total_cost_usd": round(total_cost, 6),
            "traces": [
                {
                    "chapter": t.chapter_number,
                    "status": t.status,
                    "qa_passed": t.qa_passed,
                }
                for t in traces
            ],
        }


def main() -> None:
    configure_logging()
    if os.getenv("MCP_ENABLED", "").lower() != "true":
        print("MCP server disabled: set MCP_ENABLED=true to run.", file=sys.stderr)
        sys.exit(1)
    if not os.getenv("MCP_API_KEY"):
        print("MCP_API_KEY is required (openssl rand -hex 32).", file=sys.stderr)
        sys.exit(1)

    import uvicorn

    app = _require_auth_middleware(mcp.streamable_http_app())
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port, log_level="info")


if __name__ == "__main__":
    main()
