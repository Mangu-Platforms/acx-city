"""Durable job queue + worker.

The queue is Postgres-backed: workers claim rows with
``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple workers never grab the same
job and a crash simply leaves the row for another worker (or the orphan sweeper)
to pick up. This replaces the old in-memory ``active_tasks`` + daemon thread.
"""
from .queue import (
    enqueue_job,
    claim_next_job,
    complete_job,
    fail_job,
    heartbeat,
    recover_orphans,
    request_cancel,
)

__all__ = [
    "enqueue_job",
    "claim_next_job",
    "complete_job",
    "fail_job",
    "heartbeat",
    "recover_orphans",
    "request_cancel",
]
