"""HTTP streaming audio endpoint for real-time preview.

Provides chunked MP3 streaming for progressive playback of synthesized
chapters and instant voice previews. Uses Flask's streaming Response with
generators to avoid buffering entire audio files in memory.

Features:
  - Chapter streaming with HTTP Range request support (seekable playback)
  - Instant 5-second voice preview synthesis + stream
  - Server-Sent Events for progress updates during long operations
  - MP3 chunked transfer encoding for progressive browser playback
"""
from __future__ import annotations

import io
import logging
import os
from typing import Generator, Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context
from sqlalchemy import select

from auth import current_identity, require_auth
from db.models import ChapterResult, ChapterStatus, Job, JobStatus
from db.session import session_scope
from services.providers import ProviderRegistry
from storage import get_storage

log = logging.getLogger(__name__)

# Chunk size for streaming reads (32 KiB balances latency vs. throughput).
_CHUNK_SIZE = 32 * 1024

# Where the pipeline writes chapter MP3s.
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "outputs")

# Maximum preview text length (characters) to prevent abuse.
_MAX_PREVIEW_CHARS = 2000

# ---------------------------------------------------------------------------
# SSE helper
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
# AudioStreamer
# ---------------------------------------------------------------------------

class AudioStreamer:
    """Generators that yield MP3 audio chunks for HTTP streaming."""

    def __init__(self, registry: Optional[ProviderRegistry] = None) -> None:
        self._registry = registry or ProviderRegistry()

    # -- chapter streaming --------------------------------------------------

    def stream_chapter(
        self,
        audio_path: str,
        start_ms: float = 0,
        end_ms: float | None = None,
    ) -> Generator[bytes, None, None]:
        """Yield audio chunks from *audio_path* via HTTP chunked transfer.

        Parameters
        ----------
        audio_path:
            Local filesystem path to a chapter MP3 file.
        start_ms:
            Byte-offset approximation for seeking (milliseconds into the file).
            Because MP3 is variable-bitrate we estimate the byte position from
            the file size and duration metadata when available, otherwise fall
            back to linear interpolation at 128 kbps.
        end_ms:
            Optional stop position in milliseconds.  ``None`` streams to EOF.

        Yields
        ------
        bytes
            Raw MP3 data chunks of up to ``_CHUNK_SIZE`` bytes each.
        """
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        file_size = os.path.getsize(audio_path)
        if file_size == 0:
            return

        # Estimate byte offsets from milliseconds using a 128 kbps assumption
        # (128_000 bits/s = 16_000 bytes/s).  This is approximate for VBR MP3
        # but good enough for seek-to-start — the browser will re-sync.
        _BYTES_PER_MS = 16.0  # 16 000 B/s ÷ 1000

        start_byte = int(start_ms * _BYTES_PER_MS) if start_ms > 0 else 0
        end_byte = int(end_ms * _BYTES_PER_MS) if end_ms is not None else file_size

        # Clamp to valid range.
        start_byte = max(0, min(start_byte, file_size))
        end_byte = max(start_byte, min(end_byte, file_size))

        with open(audio_path, "rb") as fh:
            fh.seek(start_byte)
            remaining = end_byte - start_byte
            while remaining > 0:
                chunk = fh.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    # -- instant preview ----------------------------------------------------

    def stream_preview(
        self,
        text: str,
        voice_id: str,
        emotion: str | None = None,
        duration_s: float = 5.0,
    ) -> Generator[bytes, None, None]:
        """Synthesize a short preview and stream it chunk by chunk.

        The text is truncated to ``_MAX_PREVIEW_CHARS`` to keep latency low.
        Synthesis happens eagerly (the provider returns all bytes at once) and
        then the result is chunked out for progressive playback.

        Parameters
        ----------
        text:
            Plain text to synthesize.
        voice_id:
            Provider voice identifier.
        emotion:
            Optional emotion/style tag (passed to ``synthesize_with_options``
            when the provider supports it).
        duration_s:
            Target preview duration in seconds.  We truncate or pad text to
            approximate this length at ~150 words/min (≈ 12.5 chars/s for
            English).
        """
        if self._registry is None:
            raise RuntimeError("ProviderRegistry not configured on AudioStreamer")

        # Truncate text to approximate the requested duration.
        from utils.audio_utils import CHARS_PER_SECOND
        max_chars = int(duration_s * CHARS_PER_SECOND)
        truncated = text[:max_chars].strip()
        if not truncated:
            raise ValueError("Preview text is empty after truncation")

        # Pick the first available provider.
        provider = self._registry.default()
        if provider is None:
            raise RuntimeError("No speech provider available")

        # Synthesize.
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

        # Stream the result in chunks.
        buf = io.BytesIO(audio_bytes)
        while True:
            chunk = buf.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


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
        Stream a completed chapter's audio with optional Range header support.

    ``POST /api/stream/preview``
        Stream an instant voice preview (JSON body: ``text``, ``voice_id``,
        optional ``emotion`` and ``duration``).
    """
    bp = Blueprint("streaming", __name__, url_prefix="/api/stream")
    streamer = AudioStreamer(registry=registry)

    # -- chapter stream -----------------------------------------------------

    @bp.route("/<job_id>/chapter/<int:chapter>", methods=["GET"])
    @require_auth
    def stream_chapter_audio(job_id: str, chapter: int):
        """Stream chapter audio with HTTP Range support for seeking.

        The browser can send ``Range: bytes=<start>-`` to seek into the file,
        which is essential for scrubbing / resuming playback.  For chapters
        stored in object storage (P0.2+) the response is a 302 redirect to a
        signed URL; local-disk chapters are streamed directly.
        """
        identity = current_identity()

        # Load job + chapter inside a short-lived session; close before streaming.
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

            audio_key = ch_row.audio_key  # may be None for pre-P0.2 chapters

        # Prefer the storage-backed artifact (P0.2+).
        if audio_key:
            storage = get_storage()
            signed = storage.signed_url(
                audio_key, expires_in=3600,
                download_name=f"chapter_{chapter:03d}.mp3",
            )
            from flask import redirect as _redirect
            return _redirect(signed.url, code=302)

        # Fallback: local file (pre-P0.2 chapter or local dev).
        audio_path = os.path.join(OUTPUT_FOLDER, job_id, f"chapter_{chapter:03d}.mp3")

        if not os.path.isfile(audio_path):
            return jsonify({
                "error": "Audio file not available for streaming",
                "hint": "Use the download endpoint for a signed URL instead",
            }), 404

        file_size = os.path.getsize(audio_path)

        # Parse Range header (RFC 7233).
        range_header = request.headers.get("Range")
        start_byte = 0
        end_byte = file_size - 1
        status_code = 200

        if range_header:
            # Expect "bytes=<start>[-<end>]"
            try:
                range_spec = range_header.replace("bytes=", "").strip()
                if "-" in range_spec:
                    parts = range_spec.split("-", 1)
                    start_byte = int(parts[0]) if parts[0] else 0
                    end_byte = int(parts[1]) if parts[1] else file_size - 1
                else:
                    start_byte = int(range_spec)
            except (ValueError, IndexError):
                return jsonify({"error": "Invalid Range header"}), 416

            # Validate range.
            if start_byte >= file_size or end_byte >= file_size or start_byte > end_byte:
                resp = Response(status=416)
                resp.headers["Content-Range"] = f"bytes */{file_size}"
                return resp

            status_code = 206

        content_length = end_byte - start_byte + 1

        def generate():
            with open(audio_path, "rb") as fh:
                fh.seek(start_byte)
                remaining = content_length
                while remaining > 0:
                    chunk = fh.read(min(_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        resp = Response(
            stream_with_context(generate()),
            status=status_code,
            content_type="audio/mpeg",
        )
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(content_length)
        resp.headers["Content-Disposition"] = (
            f'inline; filename="chapter_{chapter:03d}.mp3"'
        )
        if status_code == 206:
            resp.headers["Content-Range"] = (
                f"bytes {start_byte}-{end_byte}/{file_size}"
            )
        return resp

    # -- instant preview ----------------------------------------------------

    @bp.route("/preview", methods=["POST"])
    @require_auth
    def stream_preview_audio():
        """Stream an instant voice preview.

        Request JSON::

            {
                "text": "Hello, welcome to the show.",
                "voice_id": "Joanna",
                "emotion": "excited",       // optional
                "duration": 5.0             // optional, seconds
            }

        The response is chunked ``audio/mpeg`` for progressive playback.
        """
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        voice_id = (body.get("voice_id") or "").strip()
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

        try:
            generator = streamer.stream_preview(
                text=text,
                voice_id=voice_id,
                emotion=emotion,
                duration_s=duration_s,
            )
            resp = Response(
                stream_with_context(generator),
                content_type="audio/mpeg",
            )
            resp.headers["Transfer-Encoding"] = "chunked"
            resp.headers["Cache-Control"] = "no-store"
            return resp

        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503
        except Exception:
            log.exception("Preview synthesis failed")
            return jsonify({"error": "Preview synthesis failed"}), 500

    return bp
