"""Retention & lifecycle: delete stored assets (and optionally rows) past a TTL.

Two entry points:
  * ``delete_job_assets`` — removes a single job's stored outputs (used on explicit
    delete and by the sweeper).
  * ``sweep_expired`` — deletes assets for terminal jobs older than the retention
    window; run periodically by the worker.

Retention window resolution: per-org ``retention_days`` overrides the global
``RETENTION_DAYS`` env (0 = keep forever).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.base import utcnow
from db.models import Job, JobStatus, Organization
from storage import get_storage
from storage.base import StorageError

log = logging.getLogger("audiobook.retention")

DEFAULT_RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "0"))  # 0 = keep forever


def _as_aware(dt: datetime) -> datetime:
    """Treat naive datetimes (SQLite round-trips) as UTC so comparisons are safe."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def retention_days_for(session: Session, job: Job) -> int:
    org = session.get(Organization, job.organization_id)
    if org is not None and org.retention_days is not None:
        return org.retention_days
    return DEFAULT_RETENTION_DAYS


def delete_job_assets(session: Session, job: Job) -> int:
    """Delete a job's stored objects. Returns how many keys were removed.

    Clears the key columns so the row no longer references deleted objects.
    """
    storage = get_storage()
    removed = 0
    for attr in ("output_mp3_key", "output_m4b_key"):
        key = getattr(job, attr)
        if key:
            try:
                storage.delete(key)
                removed += 1
            except StorageError as e:  # best-effort; log and continue
                log.warning("failed to delete %s for job %s: %s", key, job.id, e)
            setattr(job, attr, None)
    # Legacy local paths, if any.
    job.output_mp3 = None
    job.output_m4b = None
    session.flush()
    return removed


def sweep_expired(session: Session, delete_rows: Optional[bool] = None) -> dict:
    """Delete assets for terminal jobs past their retention window.

    ``delete_rows`` (default from RETENTION_DELETE_ROWS env) also removes the job
    rows; otherwise rows are kept for audit and only the heavy assets are purged.
    Returns a summary dict.
    """
    if delete_rows is None:
        delete_rows = os.getenv("RETENTION_DELETE_ROWS", "false").lower() in ("1", "true", "yes")

    now = utcnow()
    terminal = (JobStatus.succeeded, JobStatus.failed, JobStatus.canceled, JobStatus.needs_review)
    candidates = session.execute(
        select(Job).where(Job.status.in_(terminal))
    ).scalars().all()

    jobs_swept = 0
    keys_removed = 0
    rows_deleted = 0
    for job in candidates:
        days = retention_days_for(session, job)
        if days <= 0:
            continue  # keep forever
        if job.updated_at and _as_aware(job.updated_at) > now - timedelta(days=days):
            continue  # still within retention
        keys_removed += delete_job_assets(session, job)
        jobs_swept += 1
        if delete_rows:
            session.delete(job)
            rows_deleted += 1

    if jobs_swept:
        session.flush()
        log.info("retention sweep: %d job(s), %d object(s) removed, %d row(s) deleted",
                 jobs_swept, keys_removed, rows_deleted)
    return {"jobs_swept": jobs_swept, "keys_removed": keys_removed, "rows_deleted": rows_deleted}
