"""Standalone durable worker process.

Run it separately from the web server:
    python worker.py

Lifecycle:
  1. On startup, recover any orphaned jobs (workers that died mid-run).
  2. Loop: claim the next queued job (FOR UPDATE SKIP LOCKED), run the pipeline,
     heartbeat the lock, and record success/failure with retry+backoff.
  3. Handle SIGTERM/SIGINT for graceful shutdown (finish nothing new, stop soon).

Scale out by running multiple worker processes; SKIP LOCKED guarantees each job
is claimed by exactly one worker.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid

from db import init_engine, session_scope
from jobs import queue as q
from jobs.pipeline import JobCanceled, run_job
from observability import configure_logging, init_sentry, request_id_var
from services.voice_city import voice_optimizer as voice_optimizer

configure_logging()
init_sentry()
log = logging.getLogger("audiobook.worker")

try:
    POLL_INTERVAL = float(os.getenv("WORKER_POLL_SECONDS", "2"))
    ORPHAN_SWEEP_INTERVAL = float(os.getenv("WORKER_ORPHAN_SWEEP_SECONDS", "60"))
    RETENTION_SWEEP_INTERVAL = float(os.getenv("WORKER_RETENTION_SWEEP_SECONDS", "3600"))
except ValueError as e:
    import sys
    print(f"Error: Invalid worker configuration: {e}", file=sys.stderr)
    sys.exit(1)

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("received signal %s, shutting down after current job", signum)
    _shutdown = True


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def process_one(worker_id: str) -> bool:
    """Claim and run a single job. Returns True if a job was processed."""
    # Claim in its own committed transaction so the lock is durable before work.
    with session_scope() as session:
        job = q.claim_next_job(session, worker_id)
        if job is None:
            return False
        job_id = job.id

    # Correlate every log line for this job under its id.
    request_id_var.set(job_id)

    # Run the pipeline in a session; commit progress incrementally inside run_job.
    with session_scope() as session:
        from db.models import Job  # local import to avoid cycles at module load

        job = session.get(Job, job_id)

        def should_continue() -> bool:
            # Refresh lock/cancel state on its own connection.
            return q.heartbeat(session, job, worker_id)

        try:
            gate_passed = run_job(session, job, should_continue)
            if gate_passed:
                q.complete_job(session, job, worker_id)
            else:
                q.hold_for_review(session, job, worker_id)
        except JobCanceled:
            from db.models import JobStatus
            job.status = JobStatus.canceled
            job.locked_by = None
            job.locked_at = None
            q._close_attempt(session, job, worker_id, outcome="canceled")
            log.info("job %s canceled", job_id)
        except Exception as e:  # noqa: BLE001
            session.rollback()
            # Re-open a clean transaction to record the failure.
            with session_scope() as s2:
                j2 = s2.get(Job, job_id)
                q.fail_job(s2, j2, worker_id, str(e))
            log.exception("job %s failed", job_id)
    return True


def process_voice_city_one(worker_id: str) -> bool:
    # Claim and run one persistent-identity optimization job.
    with session_scope() as session:
        job = voice_optimizer.claim_next_job(session, worker_id)
        if job is None:
            return False
        job_id = job.id

    request_id_var.set(job_id)
    with session_scope() as session:
        from db.voice_models import VoiceCityGenerationJob

        job = session.get(VoiceCityGenerationJob, job_id)
        if job is None:
            log.error("Voice City optimization job %s disappeared after claim", job_id)
            return True
        try:
            voice_optimizer.run_optimization_job(session, job, worker_id=worker_id)
        except voice_optimizer.OptimizationCanceled:
            voice_optimizer.mark_canceled(session, job, worker_id)
            log.info("Voice City optimization job %s canceled", job_id)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            with session_scope() as retry_session:
                retry_job = retry_session.get(VoiceCityGenerationJob, job_id)
                voice_optimizer.fail_job(retry_session, retry_job, worker_id, str(exc))
            log.exception("Voice City optimization job %s failed", job_id)
    return True


def main() -> None:
    init_engine()
    worker_id = _worker_id()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("worker %s starting", worker_id)

    # Startup orphan recovery (restart safety).
    with session_scope() as session:
        q.recover_orphans(session)
        voice_optimizer.recover_orphans(session)

    last_sweep = time.monotonic()
    last_retention = time.monotonic()
    while not _shutdown:
        did_work = False
        try:
            did_work = process_one(worker_id)
            if not did_work:
                did_work = process_voice_city_one(worker_id)
        except Exception:  # noqa: BLE001
            log.exception("unexpected error in worker loop")

        now = time.monotonic()
        if now - last_sweep >= ORPHAN_SWEEP_INTERVAL:
            with session_scope() as session:
                q.recover_orphans(session)
                voice_optimizer.recover_orphans(session)
            last_sweep = now

        if now - last_retention >= RETENTION_SWEEP_INTERVAL:
            try:
                from jobs.retention import sweep_expired
                with session_scope() as session:
                    sweep_expired(session)
            except Exception:  # noqa: BLE001
                log.exception("retention sweep failed")
            last_retention = now

        if not did_work:
            time.sleep(POLL_INTERVAL)

    log.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
