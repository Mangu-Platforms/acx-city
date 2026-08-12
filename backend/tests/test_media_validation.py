"""P1.1: media validation between synthesis and QC.

Gate (as strengthened):
  - each of the five bad-artifact shapes is rejected by the specific rule it
    targets — asserted on the rejection REASON, not just the rejection;
  - a rejected artifact leaves chapter state unchanged and triggers exactly
    one retry;
  - a validation-triggered retry bills exactly one UsageEvent per unit;
  - poisoned cache entries are detected on HIT, evicted, and re-synthesized;
  - the QC gate holds a job on REAL failing audio (not fabricated QC dicts);
  - resume reuses storage audio with zero new UsageEvents (the P0.2 money
    metric, real-audio edition).

No stub_pipeline anywhere in this file: everything runs the real audio path.
"""
import io
import os
import shutil

import pytest
from pydub import AudioSegment
from sqlalchemy import func, select

from db.base import utcnow
from db.session import session_scope
from db import models as m
from jobs import queue as q
from services.media_validation import validate_media
from services.providers.fake_provider import FakeSpeechProvider
from worker import process_one

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe required",
)

FILLER = "The quick brown fox jumps over the lazy dog again and again. " * 4

FIVE_SHAPES = [
    ("invalid_audio", "decode_failed"),
    ("truncated_audio", "truncated"),
    ("silent_audio", "silent"),
    ("wrong_duration", "implausible_duration"),
    ("wrong_format", "wrong_format"),
]


@pytest.fixture(autouse=True)
def _reset_fake_providers():
    """The registry providers are process-wide singletons; reset their
    scripted state so one test's mode_sequence can't leak into the next."""
    yield
    import jobs.pipeline as pl
    for name in ("fake", "fake-paid"):
        p = pl._registry.get(name)
        if p is not None:
            p.mode_sequence = None
            p.mode = "success"
            p.fail_after_n_calls = None
            p.calls = 0


def _seed_job(session, source_text, provider="fake-paid", voice="fake-a",
              formats="mp3"):
    org = m.Organization(name="Org")
    user = m.User(email=f"u{utcnow().timestamp()}@x.com", password_hash="h")
    session.add_all([org, user])
    session.flush()
    session.add(m.Membership(user_id=user.id, organization_id=org.id, role=m.Role.owner))
    proj = m.Project(organization_id=org.id, created_by=user.id, title="B",
                     source_text=source_text)
    session.add(proj)
    session.flush()
    job = m.Job(organization_id=org.id, project_id=proj.id, provider=provider,
                voice_id=voice, formats=formats)
    q.enqueue_job(session, job)
    return job.id, org.id


def _drain(max_attempts=10):
    """Run the worker until the queue is empty.

    A failing job is requeued with a backoff (Job.available_at in the
    future); collapse the backoff so the next attempt is claimable now —
    tests care about attempt semantics, not wall-clock delays.
    """
    for n in range(max_attempts):
        if not process_one(f"mv-worker-{n}"):
            with session_scope() as s:
                waiting = s.execute(
                    select(m.Job).where(m.Job.status == m.JobStatus.queued)
                ).scalars().all()
                if not waiting:
                    return
                for j in waiting:
                    j.available_at = utcnow()


def _usage_count(session, org_id):
    return session.execute(
        select(func.count()).select_from(m.UsageEvent)
        .where(m.UsageEvent.organization_id == org_id)
    ).scalar()


# --------------------------------------------------------------------------- #
# Unit: each artifact shape → its targeted rule
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode,expected_reason", FIVE_SHAPES)
def test_bad_artifact_rejected_by_its_targeted_rule(tmp_path, mode, expected_reason):
    data = FakeSpeechProvider().synthesize(f"[fake:{mode}]{FILLER}", "fake-a")
    p = tmp_path / "artifact.mp3"
    p.write_bytes(data)
    res = validate_media(str(p), expected_chars=len(FILLER))
    assert not res.ok
    assert res.reason == expected_reason, (
        f"{mode} must be caught by {expected_reason}, was caught by {res.reason}"
    )


def test_good_artifact_passes(tmp_path):
    data = FakeSpeechProvider().synthesize(FILLER, "fake-a")
    p = tmp_path / "good.mp3"
    p.write_bytes(data)
    res = validate_media(str(p), expected_chars=len(FILLER))
    assert res.ok, f"valid audio rejected: {res.reason}: {res.detail}"


def test_missing_and_empty(tmp_path):
    assert validate_media(str(tmp_path / "nope.mp3")).reason == "missing"
    p = tmp_path / "zero.mp3"
    p.write_bytes(b"")
    assert validate_media(str(p)).reason == "empty"


def test_quiet_and_gappy_pass_validation(tmp_path):
    """Quiet (-51 dBFS) and gappy (70% silence) audio are QC's business,
    not validation rejects — the hard silent threshold is -60 dBFS."""
    for mode in ("quiet_audio", "gappy_audio"):
        data = FakeSpeechProvider().synthesize(f"[fake:{mode}]{FILLER}", "fake-a")
        p = tmp_path / f"{mode}.mp3"
        p.write_bytes(data)
        res = validate_media(str(p), expected_chars=len(FILLER))
        assert res.ok, f"{mode} should pass validation, got {res.reason}"


# --------------------------------------------------------------------------- #
# Pipeline: rejection reason surfaces; chapter state does not advance
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode,expected_reason", FIVE_SHAPES)
def test_pipeline_rejects_and_chapter_does_not_advance(engine, mode, expected_reason):
    text = f"Chapter 1\n[fake:{mode}]{FILLER}{mode}"
    with session_scope() as s:
        jid, org_id = _seed_job(s, text)
    _drain()
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.failed, f"job should fail, got {job.status}"
        assert expected_reason in (job.error or ""), (
            f"job.error must carry the rejection reason {expected_reason!r}: "
            f"{job.error!r}"
        )
        rows = list(job.chapters)
        assert all(c.status != m.ChapterStatus.done for c in rows), (
            "rejected chapter must not advance to done"
        )
        assert all(not c.audio_key for c in rows), "no durable artifact may exist"
        assert not job.output_mp3_key, "rejected audio must never reach assembly"
        # A rejected artifact must never create a UsageEvent.
        assert _usage_count(s, org_id) == 0


# --------------------------------------------------------------------------- #
# Exactly one retry; exactly one UsageEvent
# --------------------------------------------------------------------------- #

def test_rejected_artifact_triggers_exactly_one_retry_and_bills_once(engine):
    text = "Chapter 1\n" + FILLER
    with session_scope() as s:
        jid, org_id = _seed_job(s, text)
    import jobs.pipeline as pl
    fake_paid = pl._registry.get("fake-paid")
    fake_paid.calls = 0
    fake_paid.mode_sequence = ["invalid_audio"]  # then falls back to success

    assert process_one("mv-retry-worker") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded, job.error
        assert fake_paid.calls == 2, (
            f"one rejection must trigger exactly one retry (2 calls), "
            f"got {fake_paid.calls}"
        )
        assert _usage_count(s, org_id) == 1, (
            "validation-triggered retry must bill exactly once"
        )
        rows = list(job.chapters)
        assert rows and all(c.status == m.ChapterStatus.done for c in rows)
        assert all(c.qc_policy_version for c in rows), (
            "chapters must record the QC policy version they were built under"
        )


# --------------------------------------------------------------------------- #
# Cache poisoning: detected on hit, evicted, re-synthesized
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode,expected_reason", FIVE_SHAPES)
def test_poisoned_cache_hit_is_evicted_and_resynthesized(engine, mode, expected_reason):
    import jobs.pipeline as pl
    text = f"Chapter 1\n{FILLER}cache-{mode}"

    # Job A populates the cache; snapshot which entries it created.
    before = set(os.listdir(pl._cache.cache_dir))
    with session_scope() as s:
        jid_a, org_a = _seed_job(s, text)
    assert process_one("mv-cache-a") is True
    with session_scope() as s:
        assert s.get(m.Job, jid_a).status == m.JobStatus.succeeded
        usage_a = _usage_count(s, org_a)
        assert usage_a >= 1
    new_entries = set(os.listdir(pl._cache.cache_dir)) - before
    assert new_entries, "job A must have written cache entries"

    # Poison every entry job A created with this shape's bad artifact.
    bad = FakeSpeechProvider().synthesize(f"[fake:{mode}]{FILLER}", "fake-a")
    for name in new_entries:
        with open(os.path.join(pl._cache.cache_dir, name), "wb") as f:
            f.write(bad)

    # Job B, same text, different org: hits the poisoned entries.
    with session_scope() as s:
        jid_b, org_b = _seed_job(s, text)
    assert process_one("mv-cache-b") is True
    with session_scope() as s:
        job_b = s.get(m.Job, jid_b)
        assert job_b.status == m.JobStatus.succeeded, (
            f"poisoned cache must be evicted and re-synthesized, "
            f"job failed: {job_b.error}"
        )
        # Re-synthesis is real work: billed exactly once per chunk for org B.
        assert _usage_count(s, org_b) == usage_a
        # The chapter artifact in storage decodes.
        from storage import get_storage
        for c in job_b.chapters:
            seg = AudioSegment.from_file(
                io.BytesIO(get_storage().get_bytes(c.audio_key)), format="mp3")
            assert len(seg) > 500 and seg.dBFS > -45

    # The poisoned entries were replaced with valid audio.
    for name in new_entries:
        path = os.path.join(pl._cache.cache_dir, name)
        assert os.path.exists(path), "entry must be re-populated, not just evicted"
        with open(path, "rb") as f:
            content = f.read()
        assert content != bad, "poisoned bytes must not survive"
        seg = AudioSegment.from_file(io.BytesIO(content), format="mp3")
        assert len(seg) > 0


# --------------------------------------------------------------------------- #
# QC gate on REAL audio (re-earns the matrix row demoted post-P1.0)
# --------------------------------------------------------------------------- #

def test_qc_block_holds_job_on_real_gappy_audio(engine, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "block")
    text = f"Chapter 1\n[fake:gappy_audio]{FILLER * 3}"
    with session_scope() as s:
        jid, _ = _seed_job(s, text, provider="fake")
    assert process_one("mv-qc-worker") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.needs_review, (
            f"block policy must hold real high-silence audio for review, "
            f"got {job.status} error={job.error}"
        )
        rows = list(job.chapters)
        assert rows and rows[0].qc_passed is False
        assert "silence" in (rows[0].qc_issues or "").lower()


def test_qc_warn_passes_real_gappy_audio(engine, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "warn")
    text = f"Chapter 1\n[fake:gappy_audio]{FILLER * 3}"
    with session_scope() as s:
        jid, _ = _seed_job(s, text, provider="fake")
    assert process_one("mv-qc-warn-worker") is True
    with session_scope() as s:
        assert s.get(m.Job, jid).status == m.JobStatus.succeeded


# --------------------------------------------------------------------------- #
# Resume from storage: zero new UsageEvents (real-audio P0.2 money metric)
# --------------------------------------------------------------------------- #

def test_resume_reuses_storage_audio_without_rebilling(engine):
    import jobs.pipeline as pl
    # Unique text: the synthesis cache is content-addressed and shared across
    # tests, and a cache hit legitimately does not bill. Chapter bodies must
    # exceed the splitter's 500-char minimum or the heading won't split.
    text = ("Chapter 1: First\n\n" + FILLER * 3 + "resume-money first half."
            + "\n\nChapter 2: Second\n\n" + FILLER * 3 + "resume-money second half.")
    with session_scope() as s:
        jid, org_id = _seed_job(s, text)
    assert process_one("mv-resume-1") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded, job.error
        usage_first = _usage_count(s, org_id)
        assert usage_first >= 2  # at least one chunk per chapter
        mp3_key = job.output_mp3_key

    # Container replacement: local task dir gone, synthesis cache gone.
    task_dir = os.path.join(pl.OUTPUT_FOLDER, jid)
    shutil.rmtree(task_dir, ignore_errors=True)
    for name in os.listdir(pl._cache.cache_dir):
        os.remove(os.path.join(pl._cache.cache_dir, name))

    # Re-run the same job (chapter rows keep audio_key/audio_sha256).
    with session_scope() as s:
        job = s.get(m.Job, jid)
        job.status = m.JobStatus.queued
        job.locked_by = None
        job.progress = 0
    assert process_one("mv-resume-2") is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded, job.error
        assert _usage_count(s, org_id) == usage_first, (
            "resume from storage must not create new UsageEvents — "
            "that count is the money metric"
        )
        # And the re-assembled export still decodes.
        from storage import get_storage
        seg = AudioSegment.from_file(
            io.BytesIO(get_storage().get_bytes(job.output_mp3_key)), format="mp3")
        assert len(seg) > 1000 and seg.dBFS > -45
