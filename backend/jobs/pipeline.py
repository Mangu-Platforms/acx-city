"""Audiobook production pipeline, decoupled from the web layer.

This is the same chapter-by-chapter synthesis / QC / assembly logic that used to
live inside app.py's AudiobookProducer, but it now:
  * reads its inputs from a durable Job row (not an in-memory dict),
  * persists per-chapter progress to the DB as it goes (so a restart resumes
    from the last committed state instead of losing everything),
  * checks a cooperative cancel/heartbeat callback between chapters.
"""
from __future__ import annotations

import logging
import os
from time import sleep
from typing import Callable

from sqlalchemy.orm import Session

from billing import record_usage
from db.base import utcnow
from db.models import ChapterResult, ChapterStatus, Job
from services.providers import ProviderRegistry
from services.synthesis_cache import SynthesisCache
from services.text_processor import TextProcessor
from storage import get_storage
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


def _synthesize_with_retry(provider, chunk: str, voice_id: str, engine: str) -> bytes:
    """Synthesize one chunk with exponential-backoff retry.

    Retries on any exception up to _CHUNK_MAX_ATTEMPTS times before re-raising.
    This keeps a single network hiccup from failing the entire job.
    """
    last_exc: Exception | None = None
    for attempt in range(_CHUNK_MAX_ATTEMPTS):
        try:
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
    progress_per_chapter = 75 / max(len(chapters), 1)

    ch_rows = {c.index: c for c in job.chapters}

    for i, chapter in enumerate(chapters):
        if not should_continue():
            raise JobCanceled()

        row = ch_rows[i]
        if row.status == ChapterStatus.done:
            # Resume: chapter already assembled in a previous attempt.
            path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
            if os.path.exists(path):
                chapter_files.append(path)
                chapter_titles.append(chapter["title"])
                continue

        row.status = ChapterStatus.processing
        job.current_chapter = i + 1
        session.commit()

        clean = _text.preprocess_text(chapter["text"])
        if not clean:
            row.status = ChapterStatus.skipped
            session.commit()
            continue

        chunks = _text.chunk_for_provider(clean, provider.max_chars)
        row.total_chunks = len(chunks)

        chunk_files = []
        for chunk in chunks:
            key = _cache.key(provider.name, job.voice_id, job.engine, chunk)
            cached = _cache.get(key)
            if cached:
                chunk_files.append(cached)
                row.cached_chunks += 1
                job.cached_chunks += 1
            else:
                # Fix #1: retry on transient network/provider errors so a single
                # hiccup doesn't fail the whole job.
                audio = _synthesize_with_retry(provider, chunk, job.voice_id, job.engine)
                chunk_files.append(_cache.put(key, audio))
                job.synthesized_chunks += 1
                # Cost ledger: only newly synthesized (not cached) chunks are
                # billable, and only for paid providers.
                if provider.paid:
                    record_usage(
                        session, job.organization_id, provider.name, len(chunk),
                        provider.cost_per_million_chars, job_id=job.id,
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
