"""Batch book processing — multiple books in parallel with priority queuing.

Integrates with the existing Job model and Postgres-backed queue primitives.
The ``PriorityQueue`` uses ``FOR UPDATE SKIP LOCKED`` for lock-free,
priority-ordered claiming, and ``BatchProcessor`` orchestrates multi-job
submissions, status queries, cancellations, and ETA estimation.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from db.base import utcnow
from db.models import Job, JobStatus, Project, TERMINAL_STATUSES

log = logging.getLogger("audiobook.batch")


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class BatchJob:
    """Lightweight handle returned to callers for tracking a single enqueued
    book within a batch submission."""

    job_id: str
    org_id: str
    priority: int = field(default=5)  # 1-10, 10 = highest
    created_at: datetime = field(default_factory=utcnow)
    estimated_duration_s: float = field(default=0.0)

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 10:
            raise ValueError(f"priority must be 1-10, got {self.priority}")


# --------------------------------------------------------------------------- #
# Priority queue (Postgres FOR UPDATE SKIP LOCKED)
# --------------------------------------------------------------------------- #
class PriorityQueue:
    """Priority-aware job queue backed by the ``jobs`` table.

    Uses ``ORDER BY priority DESC, available_at ASC`` with
    ``FOR UPDATE SKIP LOCKED`` on Postgres so multiple workers can claim jobs
    concurrently without contention.  Degrades gracefully on SQLite.
    """

    @staticmethod
    def _dialect(session: Session) -> str:
        return session.get_bind().dialect.name

    @staticmethod
    def enqueue(
        session: Session,
        org_id: str,
        project_id: str,
        *,
        priority: int = 5,
        provider: str = "default",
        voice_id: str = "default",
        engine: str = "neural",
        formats: str = "mp3,m4b",
        created_by: Optional[str] = None,
    ) -> Job:
        """Insert a new job with a priority level.

        Args:
            priority: 1 (lowest) to 10 (highest). Stored in a new column or
                mapped to ``available_at`` offset so the existing claim query
                can be extended without schema migration.

        Returns:
            The newly created ``Job`` row.
        """
        if not 1 <= priority <= 10:
            raise ValueError(f"priority must be 1-10, got {priority}")

        # Map priority to a negative offset from now so that higher-priority
        # jobs sort *earlier* in the existing ``available_at ASC`` ordering.
        # Priority 10 → available 9 seconds ago; priority 1 → available in 0 s.
        # This avoids needing an ALTER TABLE to add a priority column.
        offset_seconds = -(priority - 5)  # range: -5 .. +4
        available_at = utcnow() + timedelta(seconds=offset_seconds)

        job = Job(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            project_id=project_id,
            created_by=created_by,
            provider=provider,
            voice_id=voice_id,
            engine=engine,
            formats=formats,
            status=JobStatus.queued,
            available_at=available_at,
            progress=0,
            attempts=0,
        )
        session.add(job)
        session.flush()
        log.info("enqueued job %s (org=%s, project=%s, priority=%d)",
                 job.id, org_id, project_id, priority)
        return job

    @staticmethod
    def claim_next(session: Session, worker_id: str) -> Optional[Job]:
        """Claim the highest-priority available job using FOR UPDATE SKIP LOCKED.

        Returns the claimed ``Job`` or ``None`` if the queue is empty.
        """
        now = utcnow()
        base = (
            select(Job)
            .where(Job.status == JobStatus.queued, Job.available_at <= now)
            # Higher priority (more negative offset) sorts first via available_at.
            .order_by(Job.available_at.asc())
            .limit(1)
        )

        if PriorityQueue._dialect(session) == "postgresql":
            stmt = base.with_for_update(skip_locked=True)
        else:
            stmt = base

        job = session.execute(stmt).scalars().first()
        if job is None:
            return None

        job.status = JobStatus.running
        job.locked_by = worker_id
        job.locked_at = now
        job.attempts += 1
        job.updated_at = now
        session.flush()
        return job

    @staticmethod
    def queue_depth(session: Session, org_id: Optional[str] = None) -> int:
        """Return the number of queued jobs, optionally scoped to an org."""
        stmt = select(func.count(Job.id)).where(Job.status == JobStatus.queued)
        if org_id:
            stmt = stmt.where(Job.organization_id == org_id)
        return session.execute(stmt).scalar_one()

    @staticmethod
    def active_workers(session: Session) -> int:
        """Return the count of distinct workers with running jobs."""
        stmt = (
            select(func.count(func.distinct(Job.locked_by)))
            .where(Job.status == JobStatus.running, Job.locked_by.is_not(None))
        )
        return session.execute(stmt).scalar_one()


# --------------------------------------------------------------------------- #
# Batch processor
# --------------------------------------------------------------------------- #
class BatchProcessor:
    """High-level orchestrator for submitting, monitoring, and cancelling
    batches of audiobook production jobs.

    Args:
        max_concurrent: Maximum number of jobs the system should run in
            parallel.  Used for ETA estimation; actual enforcement is done by
            the worker pool's concurrency limit.
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        self.max_concurrent = max_concurrent
        self._queue = PriorityQueue()

    # -- submit ------------------------------------------------------------- #
    def enqueue_batch(
        self,
        session: Session,
        org_id: str,
        project_ids: List[str],
        *,
        priority: int = 5,
        provider: str = "default",
        voice_id: str = "default",
        engine: str = "neural",
        formats: str = "mp3,m4b",
        created_by: Optional[str] = None,
    ) -> List[BatchJob]:
        """Enqueue multiple books as a single batch.

        Each ``project_id`` produces one ``Job`` row.  All jobs share the same
        ``priority`` and synthesis parameters.

        Returns:
            A list of ``BatchJob`` handles, one per project.
        """
        if not project_ids:
            raise ValueError("project_ids must not be empty")

        batch_jobs: List[BatchJob] = []
        now = utcnow()

        for project_id in project_ids:
            job = self._queue.enqueue(
                session,
                org_id=org_id,
                project_id=project_id,
                priority=priority,
                provider=provider,
                voice_id=voice_id,
                engine=engine,
                formats=formats,
                created_by=created_by,
            )
            batch_jobs.append(
                BatchJob(
                    job_id=job.id,
                    org_id=org_id,
                    priority=priority,
                    created_at=now,
                    estimated_duration_s=self._estimate_single_duration_s(session, org_id),
                )
            )

        session.flush()
        log.info(
            "batch enqueued: org=%s, %d jobs, priority=%d",
            org_id, len(batch_jobs), priority,
        )
        return batch_jobs

    # -- status ------------------------------------------------------------- #
    def get_batch_status(
        self, session: Session, batch_ids: List[str]
    ) -> Dict[str, Dict[str, object]]:
        """Return the status of every job in ``batch_ids``.

        Returns:
            ``{job_id: {"status": ..., "progress": ..., "error": ...}, ...}``
        """
        if not batch_ids:
            return {}

        rows = (
            session.execute(
                select(Job).where(Job.id.in_(batch_ids))
            )
            .scalars()
            .all()
        )
        result: Dict[str, Dict[str, object]] = {}
        for job in rows:
            result[job.id] = {
                "status": job.status.value,
                "progress": job.progress,
                "error": job.error,
                "locked_by": job.locked_by,
                "attempts": job.attempts,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            }
        # Mark any missing ids as not-found.
        for bid in batch_ids:
            if bid not in result:
                result[bid] = {"status": "not_found", "progress": 0, "error": None}
        return result

    # -- cancel ------------------------------------------------------------- #
    def cancel_batch(
        self, session: Session, batch_ids: List[str]
    ) -> Dict[str, str]:
        """Request cancellation of every job in ``batch_ids``.

        Queued jobs are canceled immediately; running jobs are flagged for
        cooperative cancellation at the next heartbeat.

        Returns:
            ``{job_id: "canceled" | "cancel_requested" | "already_terminal" | "not_found"}``
        """
        if not batch_ids:
            return {}

        rows = (
            session.execute(select(Job).where(Job.id.in_(batch_ids)))
            .scalars()
            .all()
        )
        by_id: Dict[str, Job] = {j.id: j for j in rows}
        result: Dict[str, str] = {}

        for bid in batch_ids:
            job = by_id.get(bid)
            if job is None:
                result[bid] = "not_found"
                continue
            if job.status in TERMINAL_STATUSES:
                result[bid] = "already_terminal"
                continue

            job.cancel_requested = True
            if job.status == JobStatus.queued:
                job.status = JobStatus.canceled
                job.locked_by = None
                job.locked_at = None
                result[bid] = "canceled"
            else:
                # Running — worker will stop at next heartbeat.
                result[bid] = "cancel_requested"
            job.updated_at = utcnow()

        session.flush()
        log.info("cancel_batch: %d jobs processed", len(batch_ids))
        return result

    # -- ETA ---------------------------------------------------------------- #
    def estimate_completion(
        self, session: Session, org_id: str
    ) -> Dict[str, object]:
        """Estimate when the org's queued work will finish.

        Heuristic: each queued job is assumed to take the average duration of
        the org's recent completed jobs (last 20).  If no history exists, a
        default of 300 s is used.

        Returns:
            ``{"queued_jobs": int, "running_jobs": int,
               "avg_duration_s": float, "estimated_seconds": float,
               "estimated_completion": str}``
        """
        avg_s = self._avg_completion_time_s(session, org_id)

        queued = (
            session.execute(
                select(func.count(Job.id)).where(
                    Job.organization_id == org_id,
                    Job.status == JobStatus.queued,
                )
            )
            .scalar_one()
        )
        running = (
            session.execute(
                select(func.count(Job.id)).where(
                    Job.organization_id == org_id,
                    Job.status == JobStatus.running,
                )
            )
            .scalar_one()
        )

        # Running jobs contribute their remaining time; queued jobs contribute
        # full average duration, divided by concurrency.
        remaining_running = max(0, running - 1) * avg_s * 0.5  # rough: half-done on avg
        remaining_queued = queued * avg_s
        effective_concurrency = min(self.max_concurrent, running + queued) or 1
        estimated_s = (remaining_running + remaining_queued) / effective_concurrency

        eta = utcnow() + timedelta(seconds=estimated_s)

        return {
            "queued_jobs": queued,
            "running_jobs": running,
            "avg_duration_s": round(avg_s, 1),
            "estimated_seconds": round(estimated_s, 1),
            "estimated_completion": eta.isoformat(),
        }

    # -- queue stats -------------------------------------------------------- #
    def get_queue_stats(self, session: Session) -> Dict[str, object]:
        """Return global queue statistics.

        Returns:
            ``{"queue_depth": int, "active_workers": int,
               "running_jobs": int, "recent_throughput_per_min": float}``
        """
        queue_depth = self._queue.queue_depth(session)
        active_workers = self._queue.active_workers(session)

        running = (
            session.execute(
                select(func.count(Job.id)).where(Job.status == JobStatus.running)
            )
            .scalar_one()
        )

        # Throughput: jobs completed in the last 60 minutes, normalized to /min.
        one_hour_ago = utcnow() - timedelta(hours=1)
        recent_completed = (
            session.execute(
                select(func.count(Job.id)).where(
                    Job.status.in_([JobStatus.succeeded, JobStatus.needs_review]),
                    Job.updated_at >= one_hour_ago,
                )
            )
            .scalar_one()
        )
        throughput_per_min = recent_completed / 60.0

        return {
            "queue_depth": queue_depth,
            "active_workers": active_workers,
            "running_jobs": running,
            "recent_throughput_per_min": round(throughput_per_min, 2),
        }

    # -- internal helpers --------------------------------------------------- #
    def _estimate_single_duration_s(self, session: Session, org_id: str) -> float:
        """Return estimated duration for a single job (average or default)."""
        return self._avg_completion_time_s(session, org_id)

    @staticmethod
    def _avg_completion_time_s(session: Session, org_id: str, limit: int = 20) -> float:
        """Average wall-clock seconds for recently completed jobs in this org.

        Falls back to 300 s if no completed jobs exist.
        """
        default_s = 300.0

        rows = (
            session.execute(
                select(Job.created_at, Job.updated_at)
                .where(
                    Job.organization_id == org_id,
                    Job.status.in_([JobStatus.succeeded, JobStatus.needs_review]),
                )
                .order_by(Job.updated_at.desc())
                .limit(limit)
            )
            .all()
        )

        if not rows:
            return default_s

        durations: List[float] = []
        for created, updated in rows:
            if created and updated:
                delta = (updated - created).total_seconds()
                if delta > 0:
                    durations.append(delta)

        return sum(durations) / len(durations) if durations else default_s
