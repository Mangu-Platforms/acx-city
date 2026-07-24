"""Durable job queue + worker: lifecycle, end-to-end run, restart recovery,
retry/backoff, cancellation, and (Postgres-only) concurrent claim safety.
"""
from datetime import timedelta

import pytest

from db.base import utcnow
from db.session import session_scope
from db import models as m
from jobs import queue as q
from worker import process_one


def _seed_job(session, source_text="Chapter 1\n" + ("Hello world. " * 30), formats="mp3,m4b"):
    org = m.Organization(name="Org")
    user = m.User(email=f"u{utcnow().timestamp()}@x.com", password_hash="h")
    session.add_all([org, user])
    session.flush()
    session.add(m.Membership(user_id=user.id, organization_id=org.id, role=m.Role.owner))
    proj = m.Project(organization_id=org.id, created_by=user.id, title="B", source_text=source_text)
    session.add(proj)
    session.flush()
    job = m.Job(organization_id=org.id, project_id=proj.id, provider="edge",
                voice_id="en-US-AvaNeural", formats=formats)
    q.enqueue_job(session, job)
    return job.id


def test_enqueue_claim_complete(engine):
    with session_scope() as s:
        jid = _seed_job(s)
    with session_scope() as s:
        job = q.claim_next_job(s, "w1")
        assert job.id == jid and job.status == m.JobStatus.running and job.attempts == 1
    with session_scope() as s:
        assert q.claim_next_job(s, "w2") is None  # already running
    with session_scope() as s:
        job = s.get(m.Job, jid)
        q.complete_job(s, job, "w1")
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded and job.progress == 100
        outcomes = [a.outcome for a in job.attempt_records]
        assert outcomes == ["succeeded"]


def test_worker_runs_job_end_to_end(engine, stub_pipeline):
    with session_scope() as s:
        jid = _seed_job(s)
    assert process_one("worker-e2e") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded
        assert job.progress == 100
        assert job.output_mp3 and job.output_m4b
        assert job.chapters_count >= 1
        assert all(c.status == m.ChapterStatus.done for c in job.chapters)


def test_retry_and_backoff_then_permanent_failure(engine):
    with session_scope() as s:
        jid = _seed_job(s)
        s.get(m.Job, jid).max_attempts = 2
    # attempt 1 fails -> requeued with backoff
    with session_scope() as s:
        job = q.claim_next_job(s, "w1")
        q.fail_job(s, job, "w1", "boom")
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.queued and job.attempts == 1
        # backoff scheduled in the future (compare tz-naive to be backend-agnostic;
        # SQLite drops tzinfo on round-trip).
        avail = job.available_at.replace(tzinfo=None)
        assert avail > utcnow().replace(tzinfo=None)
        job.available_at = utcnow()  # fast-forward for the test
    # attempt 2 fails -> permanent
    with session_scope() as s:
        job = q.claim_next_job(s, "w1")
        q.fail_job(s, job, "w1", "boom again")
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.failed and job.attempts == 2
        assert [a.outcome for a in job.attempt_records] == ["failed", "failed"]


def test_orphan_recovery_requeues_dead_worker_job(engine):
    with session_scope() as s:
        jid = _seed_job(s)
    with session_scope() as s:
        job = q.claim_next_job(s, "deadworker")
        job.locked_at = utcnow() - timedelta(hours=1)  # simulate death
    with session_scope() as s:
        assert q.recover_orphans(s, lease_seconds=900) == 1
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.queued and job.locked_by is None
        assert any(a.outcome == "orphaned" for a in job.attempt_records)
    # A fresh worker can now pick it up again.
    with session_scope() as s:
        assert q.claim_next_job(s, "w2").id == jid


def test_restart_resumes_completed_chapters(engine, stub_pipeline):
    """A job partially done in a prior attempt keeps finished chapters."""
    src = ("Chapter 1\n" + ("The first chapter has plenty of words here. " * 8)
           + "\n\nChapter 2\n" + ("The second chapter also has plenty of words. " * 8))
    with session_scope() as s:
        jid = _seed_job(s, source_text=src)
    # Simulate: first chapter already done on a previous (crashed) attempt.
    with session_scope() as s:
        job = s.get(m.Job, jid)
        job.chapters_count = 2
        s.add(m.ChapterResult(job_id=jid, index=0, title="Chapter 1", status=m.ChapterStatus.done))
        s.add(m.ChapterResult(job_id=jid, index=1, title="Chapter 2", status=m.ChapterStatus.pending))
    import os
    import jobs.pipeline as pl
    os.makedirs(os.path.join(pl.OUTPUT_FOLDER, jid), exist_ok=True)
    open(os.path.join(pl.OUTPUT_FOLDER, jid, "chapter_000.mp3"), "wb").write(b"ID3done")
    assert process_one("worker-resume") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded
        assert all(c.status == m.ChapterStatus.done for c in job.chapters)


def test_cancel_queued_job(engine):
    with session_scope() as s:
        jid = _seed_job(s)
        job = s.get(m.Job, jid)
        q.request_cancel(s, job)
    with session_scope() as s:
        assert s.get(m.Job, jid).status == m.JobStatus.canceled
    # A canceled job is not claimable.
    with session_scope() as s:
        assert q.claim_next_job(s, "w1") is None


def test_concurrent_claims_are_exclusive(engine, is_postgres):
    """On Postgres, two workers claiming simultaneously must not both get a job.

    Requires real row locking (FOR UPDATE SKIP LOCKED); skipped on SQLite.
    """
    if not is_postgres:
        pytest.skip("SKIP LOCKED concurrency requires Postgres")

    import threading
    from db.session import get_session

    with session_scope() as s:
        jid = _seed_job(s)

    claimed = []

    def claim(worker):
        s = get_session()
        try:
            job = q.claim_next_job(s, worker)
            s.commit()
            if job:
                claimed.append((worker, job.id))
        finally:
            s.close()

    t1 = threading.Thread(target=claim, args=("w1",))
    t2 = threading.Thread(target=claim, args=("w2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one worker got the job.
    assert len(claimed) == 1 and claimed[0][1] == jid
