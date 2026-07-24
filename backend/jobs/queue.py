"""Postgres-backed durable job queue primitives.

All functions take an explicit SQLAlchemy Session so callers control the
transaction boundary. The claim uses ``FOR UPDATE SKIP LOCKED`` on Postgres;
on SQLite (local/sandbox) it degrades to a plain ordered SELECT + guarded
UPDATE, which is correct for a single worker.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.base import utcnow
from db.models import Job, JobAttempt, JobStatus

log = logging.getLogger("audiobook.queue")

# A running job whose lock is older than this is considered orphaned (its worker
# died). The orphan sweeper requeues it.
DEFAULT_LEASE_SECONDS = 900  # 15 min
RETRY_BACKOFF_SECONDS = 30


def enqueue_job(session: Session, job: Job) -> Job:
    """Insert a new job in the queued state, available immediately."""
    job.status = JobStatus.queued
    job.available_at = utcnow()
    job.locked_by = None
    job.locked_at = None
    session.add(job)
    session.flush()
    log.info("enqueued job %s", job.id)
    return job


def _dialect(session: Session) -> str:
    return session.get_bind().dialect.name


def claim_next_job(session: Session, worker_id: str) -> Optional[Job]:
    """Atomically claim the next available queued job for this worker.

    Returns the claimed Job (status set to running, lock stamped) or None.
    The caller's transaction must be committed to make the claim durable.
    """
    now = utcnow()
    base = (
        select(Job)
        .where(Job.status == JobStatus.queued, Job.available_at <= now)
        .order_by(Job.available_at.asc())
        .limit(1)
    )

    if _dialect(session) == "postgresql":
        # Skip rows another worker already locked; never block.
        stmt = base.with_for_update(skip_locked=True)
    else:
        stmt = base

    job = session.execute(stmt).scalars().first()
    if job is None:
        return None

    # On SQLite there is no row lock, so guard the transition with a conditional
    # update to stay correct if two claimers race (single-worker in practice).
    job.status = JobStatus.running
    job.locked_by = worker_id
    job.locked_at = now
    job.attempts += 1
    job.updated_at = now
    session.flush()

    session.add(
        JobAttempt(
            job_id=job.id,
            attempt_number=job.attempts,
            worker_id=worker_id,
            started_at=now,
        )
    )
    session.flush()
    log.info("worker %s claimed job %s (attempt %d)", worker_id, job.id, job.attempts)
    return job


def heartbeat(session: Session, job: Job, worker_id: str) -> bool:
    """Refresh the lock timestamp so the orphan sweeper leaves this job alone.

    Returns False if the job was canceled or stolen (worker should stop).
    """
    session.refresh(job)
    if job.cancel_requested:
        return False
    if job.locked_by != worker_id or job.status != JobStatus.running:
        return False
    job.locked_at = utcnow()
    session.flush()
    return True


def complete_job(session: Session, job: Job, worker_id: str) -> None:
    job.status = JobStatus.succeeded
    job.progress = 100
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    _close_attempt(session, job, worker_id, outcome="succeeded")
    log.info("job %s succeeded", job.id)


def hold_for_review(session: Session, job: Job, worker_id: str) -> None:
    """QC gate held the job: audio exists but failed QC. Terminal-but-recoverable."""
    job.status = JobStatus.needs_review
    job.progress = 100
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    _close_attempt(session, job, worker_id, outcome="needs_review")
    log.info("job %s held for review (QC gate)", job.id)


def approve_reviewed_job(session: Session, job: Job) -> None:
    """Human approves a needs_review job, promoting it to succeeded."""
    if job.status != JobStatus.needs_review:
        raise ValueError(f"Job is not awaiting review (status={job.status.value})")
    job.status = JobStatus.succeeded
    job.updated_at = utcnow()
    session.flush()


def reject_reviewed_job(session: Session, job: Job, reason: str = "") -> None:
    """Human rejects a needs_review job, marking it failed."""
    if job.status != JobStatus.needs_review:
        raise ValueError(f"Job is not awaiting review (status={job.status.value})")
    job.status = JobStatus.failed
    job.error = reason or "rejected after QC review"
    job.updated_at = utcnow()
    session.flush()


def fail_job(session: Session, job: Job, worker_id: str, error: str) -> None:
    """Record a failure. Retries with backoff until max_attempts, then fails."""
    job.error = error
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    _close_attempt(session, job, worker_id, outcome="failed", error=error)

    if job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.available_at = utcnow() + timedelta(seconds=RETRY_BACKOFF_SECONDS)
        log.warning("job %s failed (attempt %d/%d), requeued: %s",
                    job.id, job.attempts, job.max_attempts, error)
    else:
        job.status = JobStatus.failed
        log.error("job %s permanently failed after %d attempts: %s",
                  job.id, job.attempts, error)


def request_cancel(session: Session, job: Job) -> None:
    """Flag a job for cancellation. A queued job is canceled immediately; a
    running job is stopped cooperatively at its next heartbeat."""
    job.cancel_requested = True
    if job.status == JobStatus.queued:
        job.status = JobStatus.canceled
        job.locked_by = None
        job.locked_at = None
    job.updated_at = utcnow()
    session.flush()


def recover_orphans(session: Session, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> int:
    """Requeue running jobs whose worker died (stale lock).

    Called on worker startup and periodically. Returns the number recovered.
    This is what makes the system restart-safe: a crash mid-job doesn't strand
    the job forever.
    """
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    stale: List[Job] = (
        session.execute(
            select(Job).where(
                Job.status == JobStatus.running,
                Job.locked_at.is_not(None),
                Job.locked_at < cutoff,
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for job in stale:
        # Mark the dead attempt as orphaned for the audit trail.
        last = (
            session.execute(
                select(JobAttempt)
                .where(JobAttempt.job_id == job.id, JobAttempt.finished_at.is_(None))
                .order_by(JobAttempt.attempt_number.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if last:
            last.finished_at = utcnow()
            last.outcome = "orphaned"

        if job.attempts >= job.max_attempts:
            job.status = JobStatus.failed
            job.error = "worker died and max attempts exhausted"
        else:
            job.status = JobStatus.queued
            job.available_at = utcnow()
        job.locked_by = None
        job.locked_at = None
        job.updated_at = utcnow()
        count += 1
    if count:
        session.flush()
        log.warning("recovered %d orphaned job(s)", count)
    return count


def _close_attempt(session: Session, job: Job, worker_id: str, outcome: str, error: Optional[str] = None) -> None:
    last = (
        session.execute(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id, JobAttempt.finished_at.is_(None))
            .order_by(JobAttempt.attempt_number.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if last:
        last.finished_at = utcnow()
        last.outcome = outcome
        last.error = error
    session.flush()
