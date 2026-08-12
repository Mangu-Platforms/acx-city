"""Chapter streaming + instant voice preview (P1.4 rewrite).

Design:
  - Chapter streaming resolves audio from the chapter's durable ``audio_key``
    only — never by rebuilding a local worker path. The response is a 302 to
    a signed URL; Range requests are honoured by the artifact server
    (``/api/files`` serves conditionally for the local backend, S3 natively).
  - Voice preview is fully synchronous against the real SpeechProvider
    interface: synthesize → validate → ``storage.put_bytes`` → return a
    signed URL as JSON. Previews are content-addressed
    (``previews/{org}/{hash}.mp3``), so identical requests reuse the stored
    artifact without re-synthesis.

The former async voice_preview design (async provider calls on Gunicorn
threads, nonexistent storage methods) was deleted, not adapted.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from flask import Blueprint, jsonify, redirect, request
from sqlalchemy import select

from auth import current_identity, require_auth
from db.models import ChapterResult, ChapterStatus, Job, JobStatus
from db.session import session_scope
from services.providers import ProviderRegistry
from storage import get_storage

log = logging.getLogger(__name__)

# Maximum preview text length (characters) to prevent abuse.
_MAX_PREVIEW_CHARS = 2000

# Signed preview links stay valid this long (seconds).
_PREVIEW_URL_TTL = 3600


# ---------------------------------------------------------------------------
# SSE helper (used by progress endpoints elsewhere)
# ---------------------------------------------------------------------------

def format_sse_event(data: dict) -> str:
    """Format a dict as a Server-Sent Events message.

    Each key becomes a separate ``field: value`` line.  A trailing blank line
    terminates the event (required by the SSE spec).

    Example::

        >>> format_sse_event({"event": "progress", "pct": 42})
        'event: progress\\ndata: {"pct": 42}\\n\\n'
    """
    import json
    payload = dict(data)  # avoid mutating caller's dict
    event = payload.pop("event", None)
    lines: list[str] = []
    if event is not None:
        lines.append(f"event: {event}")
    # Serialize remaining keys as the data payload.
    lines.append(f"data: {json.dumps(payload)}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Preview rendering
# ---------------------------------------------------------------------------

class AudioStreamer:
    """Synchronous preview renderer against the real provider registry."""

    def __init__(self, registry: Optional[ProviderRegistry] = None) -> None:
        self._registry = registry or ProviderRegistry()

    def render_preview(
        self,
        text: str,
        voice_id: str,
        emotion: str | None = None,
        duration_s: float = 5.0,
        provider_name: str | None = None,
    ) -> tuple[bytes, str]:
        """Synthesize a short preview; returns (mp3_bytes, provider_name).

        Text is truncated to approximate ``duration_s`` at the spoken-English
        pacing constant (~12.5 chars/s). Synchronous end to end: real
        providers are synchronous, and this runs on a Flask worker thread.
        """
        from utils.audio_utils import CHARS_PER_SECOND
        max_chars = int(duration_s * CHARS_PER_SECOND)
        truncated = text[:max_chars].strip()
        if not truncated:
            raise ValueError("Preview text is empty after truncation")

        if provider_name:
            provider = self._registry.get(provider_name)
            if provider is None or not provider.is_available():
                raise RuntimeError(f"Provider {provider_name!r} is unavailable")
        else:
            provider = self._registry.default()
            if provider is None:
                raise RuntimeError("No speech provider available")

        kwargs: dict = {}
        if emotion:
            kwargs["style"] = emotion
        try:
            audio_bytes = provider.synthesize_with_options(
                truncated, voice_id, **kwargs,
            )
        except TypeError:
            # Provider doesn't accept style — fall back to plain synthesis.
            audio_bytes = provider.synthesize(truncated, voice_id)
        return audio_bytes, provider.name


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

def create_streaming_blueprint(
    registry: ProviderRegistry | None = None,
) -> Blueprint:
    """Return a Flask :class:`Blueprint` exposing the streaming endpoints.

    Endpoints
    ---------
    ``GET /api/stream/<job_id>/chapter/<int:chapter>``
        302 to a signed URL for the chapter's durable artifact. The artifact
        server honours Range requests for seeking.

    ``POST /api/stream/preview``
        Synthesize (or reuse) a short preview; returns JSON with a signed
        ``url``.
    """
    bp = Blueprint("streaming", __name__, url_prefix="/api/stream")
    streamer = AudioStreamer(registry=registry)

    # -- chapter stream -----------------------------------------------------

    @bp.route("/<job_id>/chapter/<int:chapter>", methods=["GET"])
    @require_auth
    def stream_chapter_audio(job_id: str, chapter: int):
        """302 to a signed URL for the chapter's durable audio.

        Resolution is by ``audio_key`` ONLY (P1.4): a chapter without a
        durable artifact is an error state, never an excuse to guess at a
        worker's local disk.
        """
        identity = current_identity()

        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None or job.organization_id != identity.org.id:
                return jsonify({"error": "Job not found"}), 404

            if job.status != JobStatus.succeeded:
                return jsonify({"error": "Job is not completed yet"}), 409

            ch_row = session.execute(
                select(ChapterResult).where(
                    ChapterResult.job_id == job_id,
                    ChapterResult.index == chapter,
                )
            ).scalar_one_or_none()

            if ch_row is None:
                return jsonify({"error": "Chapter not found"}), 404

            if ch_row.status != ChapterStatus.done:
                return jsonify({"error": "Chapter not ready"}), 409

            audio_key = ch_row.audio_key

        if not audio_key:
            return jsonify({
                "error": "Chapter has no durable audio artifact",
                "hint": "Re-run the job; chapters are uploaded to storage on completion",
            }), 409

        storage = get_storage()
        # No download_name: the artifact server serves inline (streamable)
        # and honours Range; the download endpoint is the attachment path.
        signed = storage.signed_url(audio_key, expires_in=3600)
        return redirect(signed.url, code=302)

    # -- instant preview ----------------------------------------------------

    @bp.route("/preview", methods=["POST"])
    @require_auth
    def stream_preview_audio():
        """Synthesize a short preview and return a signed URL.

        Request JSON::

            {
                "text": "Hello, welcome to the show.",
                "voice_id": "Joanna",
                "provider": "edge",        // optional, else registry default
                "emotion": "excited",      // optional
                "duration": 5.0            // optional, seconds
            }

        Response JSON::

            {"url": "...", "provider": "edge", "cached": false}

        Previews are content-addressed per org; identical requests reuse the
        stored artifact without re-synthesis.
        """
        identity = current_identity()
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        voice_id = (body.get("voice_id") or "").strip()
        provider_name = (body.get("provider") or "").strip() or None
        emotion = body.get("emotion")
        duration_s = float(body.get("duration", 5.0))

        if not text:
            return jsonify({"error": "text is required"}), 400
        if not voice_id:
            return jsonify({"error": "voice_id is required"}), 400
        if len(text) > _MAX_PREVIEW_CHARS:
            return jsonify({
                "error": f"text exceeds {_MAX_PREVIEW_CHARS} character limit",
            }), 400

        digest = hashlib.sha256(
            f"{provider_name or 'default'}:{voice_id}:{emotion or ''}:"
            f"{duration_s}:{text}".encode()
        ).hexdigest()[:32]
        key = f"previews/{identity.org.id}/{digest}.mp3"
        storage = get_storage()

        try:
            cached = storage.exists(key)
            if not cached:
                audio_bytes, provider_used = streamer.render_preview(
                    text=text, voice_id=voice_id, emotion=emotion,
                    duration_s=duration_s, provider_name=provider_name,
                )
                storage.put_bytes(key, audio_bytes, content_type="audio/mpeg")
            else:
                provider_used = provider_name or "cached"
            signed = storage.signed_url(key, expires_in=_PREVIEW_URL_TTL)
            return jsonify({
                "url": signed.url,
                "provider": provider_used,
                "cached": cached,
            })
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503
        except Exception:
            log.exception("Preview synthesis failed")
            return jsonify({"error": "Preview synthesis failed"}), 500

    return bp
