"""Audiobook production pipeline, decoupled from the web layer.

This is the same chapter-by-chapter synthesis / QC / assembly logic that used to
live inside app.py's AudiobookProducer, but it now:
  * reads its inputs from a durable Job row (not an in-memory dict),
  * persists per-chapter progress to the DB as it goes (so a restart resumes
    from the last committed state instead of losing everything),
  * checks a cooperative cancel/heartbeat callback between chapters.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from time import sleep
from typing import Callable

from sqlalchemy.orm import Session

from billing import record_usage
from db.base import utcnow
from db.models import ChapterResult, ChapterStatus, Job
from jobs.queue import LeaseLost  # re-export so callers import from one place
from services.providers import ProviderRegistry
from services.synthesis_cache import SynthesisCache
from services.text_processor import TextProcessor
from services.voice_city.production import (
    load_voice_snapshot, prepare_directed_segments, production_manifest,
)
from storage import get_storage
from pipeline.integration import pipeline_enabled, preprocess_chapter_pipeline
from utils.audio_utils import AudioUtils

log = logging.getLogger("audiobook.pipeline")

OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "outputs")
CACHE_FOLDER = os.getenv("CACHE_FOLDER", "cache")

_registry = ProviderRegistry()
_text = TextProcessor()
_audio = AudioUtils()
_cache = SynthesisCache(CACHE_FOLDER)

# Maximum attempts and base delay (seconds) for per-chunk synthesis retries.
_CHUNK_MAX_ATTEMPTS = 3
_CHUNK_RETRY_BASE_S = 1.0


def _output_key(job: Job, filename: str) -> str:
    """Object-storage key namespaced by org + job (tenant isolation in keys)."""
    return f"org/{job.organization_id}/jobs/{job.id}/{filename}"


def resolve_qc_policy(job: Job) -> str:
    """Effective QC policy for a job: org override, else the global default."""
    org = job.project.organization if job.project else None
    if org is not None and org.qc_policy:
        return org.qc_policy
    return os.getenv("QC_POLICY", "warn").lower()


class JobCanceled(Exception):
    """Raised when a cooperative cancel is observed mid-run."""


def _upload_chapter_audio(
    job: Job, chapter_row: ChapterResult, chapter_index: int, audio_path: str
) -> str:
    """Upload chapter audio to object storage and record checksum + size on the row.

    Returns the storage key. Raises on any failure; caller decides whether to
    retry or mark the chapter pending again.
    """
    storage = get_storage()

    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Chapter audio not found: {audio_path}")

    with open(audio_path, "rb") as f:
        audio_bytes_data = f.read()
    sha256 = hashlib.sha256(audio_bytes_data).hexdigest()

    qc = _audio.qc_check(audio_path)
    if not qc.get("duration_s"):
        raise ValueError(f"Chapter {chapter_index}: audio has no decodable duration")

    key = _output_key(job, f"chapters/{chapter_index:03d}.mp3")
    storage.put_bytes(key, audio_bytes_data, content_type="audio/mpeg")

    chapter_row.audio_key = key
    chapter_row.audio_sha256 = sha256
    chapter_row.audio_bytes = len(audio_bytes_data)
    chapter_row.content_type = "audio/mpeg"

    log.info(
        "uploaded chapter %d to storage: key=%s bytes=%d sha256=%s…",
        chapter_index, key, len(audio_bytes_data), sha256[:8],
    )
    return key


def _synthesize_with_retry(provider, chunk: str, voice_id: str, engine: str, render_plan=None) -> bytes:
    """Synthesize one chunk with exponential-backoff retry.

    Retries on any exception up to _CHUNK_MAX_ATTEMPTS times before re-raising.
    This keeps a single network hiccup from failing the entire job.
    """
    last_exc: Exception | None = None
    for attempt in range(_CHUNK_MAX_ATTEMPTS):
        try:
            if render_plan is not None and hasattr(provider, "synthesize_with_options"):
                return provider.synthesize_with_options(
                    chunk, voice_id, engine=engine, rate=render_plan.rate,
                    pitch=render_plan.pitch, volume=render_plan.volume, style=render_plan.style,
                )
            return provider.synthesize(chunk, voice_id, engine)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _CHUNK_MAX_ATTEMPTS - 1:
                delay = _CHUNK_RETRY_BASE_S * (2 ** attempt)
                log.warning(
                    "chunk synthesis failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _CHUNK_MAX_ATTEMPTS, delay, exc,
                )
                sleep(delay)
    raise RuntimeError(
        f"chunk synthesis failed after {_CHUNK_MAX_ATTEMPTS} attempts"
    ) from last_exc


def run_job(session: Session, job: Job, should_continue: Callable[[], bool]) -> bool:
    """Execute one job to completion. Commits progress incrementally.

    `should_continue()` is called between chapters; if it returns False the run
    is aborted (cancel requested or lock lost). Raises on hard failure so the
    caller records the attempt and applies retry/backoff.

    Returns True if the job passes its QC gate, False if the QC policy is
    ``block`` and one or more chapters failed QC (caller holds it for review).
    """
    project = job.project
    voice_snapshot = load_voice_snapshot(session, job.id)
    provider = _registry.get(job.provider) or _registry.default()
    if not provider.is_available():
        raise RuntimeError(
            f"Provider '{provider.name}' is not available "
            "(check configuration, e.g. AWS credentials for Polly)."
        )

    chapters = _text.split_by_chapters(project.source_text)
    job.chapters_count = len(chapters)
    job.progress = max(job.progress, 5)
    _sync_chapter_rows(session, job, chapters)
    session.commit()

    task_dir = os.path.join(OUTPUT_FOLDER, job.id)
    os.makedirs(task_dir, exist_ok=True)

    chapter_files = []
    chapter_titles = []
    direction_trace = []
    progress_per_chapter = 75 / max(len(chapters), 1)

    ch_rows = {c.index: c for c in job.chapters}

    for i, chapter in enumerate(chapters):
        if not should_continue():
            raise JobCanceled()

        row = ch_rows[i]
        if row.status == ChapterStatus.done:
            # Resume: prefer durable storage copy (survives container replacement).
            if row.audio_key and row.audio_sha256:
                try:
                    audio_data = get_storage().get_bytes(row.audio_key)
                    if hashlib.sha256(audio_data).hexdigest() == row.audio_sha256:
                        path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
                        with open(path, "wb") as f:
                            f.write(audio_data)
                        chapter_files.append(path)
                        chapter_titles.append(chapter["title"])
                        log.info("resumed chapter %d from storage (key=%s)", i, row.audio_key)
                        continue
                    log.warning("chapter %d storage checksum mismatch; re-synthesizing", i)
                except Exception as e:
                    log.warning("failed to fetch chapter %d from storage: %s; falling back", i, e)
            # Fallback: local disk (works when storage unavailable or not yet uploaded).
            path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
            if os.path.exists(path):
                chapter_files.append(path)
                chapter_titles.append(chapter["title"])
                log.info("resumed chapter %d from local disk", i)
                continue

        row.status = ChapterStatus.processing
        job.current_chapter = i + 1
        session.commit()

        # Multi-agent pipeline preprocessing (when enabled)
        pipeline_meta = {}
        if pipeline_enabled():
            clean, pipeline_meta = preprocess_chapter_pipeline(
                session, job.id, i, chapter["text"], chapter["title"]
            )
        else:
            clean = _text.preprocess_text(chapter["text"])
        if not clean:
            row.status = ChapterStatus.skipped
            session.commit()
            continue

        render_tasks = []
        if voice_snapshot is not None:
            directed_segments = prepare_directed_segments(
                voice_snapshot, clean, engine=job.engine, chapter_index=i,
                chapter_title=chapter["title"],
            )
            for directed in directed_segments:
                task_provider = _registry.get(directed.provider)
                if task_provider is None:
                    raise RuntimeError(f"Unknown directed-segment provider: {directed.provider}")
                if not task_provider.is_available():
                    raise RuntimeError(
                        f"Directed-segment provider '{directed.provider}' is unavailable"
                    )
                direction_trace.append({
                    "chapter_index": i,
                    "chapter_title": chapter["title"],
                    "kind": directed.kind,
                    "speaker": directed.speaker,
                    "scene_index": directed.scene_index,
                    "sentence_index": directed.sentence_index,
                    "provider": directed.provider,
                    "provider_voice_id": directed.provider_voice_id,
                    "model_revision": directed.model_revision,
                    "voice_version_id": directed.metadata.get("voice_version_id"),
                    "voice_name": directed.metadata.get("voice_name"),
                    "identity_fingerprint": directed.identity_fingerprint,
                    "text_sha256": hashlib.sha256(directed.text.encode("utf-8")).hexdigest(),
                    "character_count": len(directed.text),
                    "source_segment_index": directed.metadata.get("source_segment_index"),
                    "source_segment_indices": directed.metadata.get("source_segment_indices"),
                })
                for segment_chunk in _text.chunk_for_provider(
                    directed.text, task_provider.max_chars
                ):
                    render_tasks.append((
                        task_provider, segment_chunk, directed.provider_voice_id,
                        directed.render_plan, directed.identity_fingerprint,
                    ))
        else:
            for plain_chunk in _text.chunk_for_provider(clean, provider.max_chars):
                render_tasks.append((provider, plain_chunk, job.voice_id, None, ""))

        row.total_chunks = len(render_tasks)
        if not render_tasks:
            row.status = ChapterStatus.skipped
            session.commit()
            continue

        chunk_files = []
        for task_provider, rendered_chunk, task_voice_id, render_plan, identity_fingerprint in render_tasks:
            cache_voice_id = task_voice_id
            if voice_snapshot is not None and render_plan is not None:
                cache_voice_id = (
                    f"{task_voice_id}:{voice_snapshot.fingerprint}:"
                    f"{identity_fingerprint}:{render_plan.cache_discriminator()}"
                )
            key = _cache.key(task_provider.name, cache_voice_id, job.engine, rendered_chunk)
            cached = _cache.get(key)
            if cached:
                chunk_files.append(cached)
                row.cached_chunks += 1
                job.cached_chunks += 1
            else:
                audio = _synthesize_with_retry(
                    task_provider, rendered_chunk, task_voice_id, job.engine,
                    render_plan=render_plan,
                )
                chunk_files.append(_cache.put(key, audio))
                job.synthesized_chunks += 1
                if task_provider.paid:
                    record_usage(
                        session, job.organization_id, task_provider.name,
                        len(rendered_chunk), task_provider.cost_per_million_chars,
                        job_id=job.id,
                    )

        chapter_path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
        # Fix #3: always go through merge_audio_files (even for 1 chunk) so
        # every chapter is re-encoded consistently and has the same gap policy.
        if not _audio.merge_audio_files(chunk_files, chapter_path, gap_duration=400):
            raise RuntimeError(f"Failed to assemble chapter {i + 1}")

        # Fix #2: normalize each chapter to a consistent loudness target before
        # QC and before assembling the final book, so volume is uniform across
        # all chapters regardless of TTS output level.
        norm_path = chapter_path + ".norm.mp3"
        if _audio.normalize_audio(chapter_path, norm_path):
            os.replace(norm_path, chapter_path)
        else:
            log.warning("loudness normalization failed for chapter %d; using raw audio", i + 1)

        qc = _audio.qc_check(chapter_path)
        row.duration_s = qc.get("duration_s")
        row.loudness_dbfs = qc.get("loudness_dbfs")
        row.peak_dbfs = qc.get("peak_dbfs")
        row.silence_ratio = qc.get("silence_ratio")
        row.clipping = qc.get("clipping")
        row.qc_passed = qc.get("passed")
        row.qc_issues = "\n".join(qc.get("issues", []))
        row.status = ChapterStatus.done

        chapter_files.append(chapter_path)
        chapter_titles.append(chapter["title"])
        job.progress = int(10 + (i + 1) * progress_per_chapter)
        job.updated_at = utcnow()
        session.commit()  # durable per-chapter checkpoint

        # Upload to object storage so a container restart can resume without re-synthesizing.
        try:
            _upload_chapter_audio(job, row, i, chapter_path)
            session.commit()
        except Exception as e:
            log.error("failed to upload chapter %d to storage: %s; will re-synthesize on retry", i, e)
            row.status = ChapterStatus.pending
            row.audio_key = None
            row.audio_sha256 = None
            session.commit()

    if not chapter_files:
        raise RuntimeError("No audio was produced (empty input?)")

    storage = get_storage()
    formats = job.format_list
    if "mp3" in formats:
        job.progress = 88
        session.commit()
        mp3_path = os.path.join(task_dir, "audiobook.mp3")
        # Fix #3: use ffmpeg concat for the final merge to avoid a second
        # encode/decode generation-loss cycle through pydub.
        if _audio.concat_audio_files(chapter_files, mp3_path, gap_ms=1500):
            key = _output_key(job, "audiobook.mp3")
            storage.put_file(key, mp3_path, content_type="audio/mpeg")
            job.output_mp3_key = key
            job.output_mp3 = mp3_path  # legacy back-compat

    if "m4b" in formats:
        job.progress = 94
        session.commit()
        m4b_path = os.path.join(task_dir, "audiobook.m4b")
        if _audio.export_m4b(
            chapter_files, chapter_titles, m4b_path,
            book_title=project.title or "Audiobook", author=project.author or "",
        ):
            key = _output_key(job, "audiobook.m4b")
            storage.put_file(key, m4b_path, content_type="audio/mp4")
            job.output_m4b_key = key
            job.output_m4b = m4b_path  # legacy back-compat

    if not (job.output_mp3_key or job.output_m4b_key):
        raise RuntimeError("No output file could be produced")

    if voice_snapshot is not None:
        manifest = production_manifest(voice_snapshot, job_id=job.id)
        manifest["direction_trace"] = direction_trace
        output_fingerprints = {}
        for output_format, output_path in (("mp3", job.output_mp3), ("m4b", job.output_m4b)):
            if output_path and os.path.exists(output_path):
                with open(output_path, "rb") as handle:
                    output_fingerprints[output_format] = hashlib.sha256(handle.read()).hexdigest()
        manifest["output_audio_fingerprints"] = output_fingerprints
        storage.put_bytes(
            _output_key(job, "voice-city-provenance.json"),
            json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    job.progress = 100
    session.commit()

    # QC gate: with policy=block, any failing chapter holds the job for review.
    policy = resolve_qc_policy(job)
    failed_chapters = [c for c in job.chapters if c.qc_passed is False]
    gate_passed = not (policy == "block" and failed_chapters)
    if not gate_passed:
        log.warning("job %s held for review: %d chapter(s) failed QC (policy=block)",
                    job.id, len(failed_chapters))
    return gate_passed


def _sync_chapter_rows(session: Session, job: Job, chapters) -> None:
    """Ensure a ChapterResult row exists for each detected chapter."""
    existing = {c.index: c for c in job.chapters}
    for i, ch in enumerate(chapters):
        if i in existing:
            existing[i].title = ch["title"]
        else:
            session.add(ChapterResult(job_id=job.id, index=i, title=ch["title"]))
    session.flush()
    session.refresh(job)
