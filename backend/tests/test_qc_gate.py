"""QC gating: policy=block holds failing jobs for review; approve/reject flow."""
import pytest

from db import models as m
from db.session import session_scope


@pytest.fixture()
def failing_qc(monkeypatch):
    """Make QC report a failure so the gate triggers.

    Patches the CLASS, never the pl._audio instance: instance-patching after
    stub_pipeline's class patch makes monkeypatch capture the stub as the
    "original" and freeze it onto the singleton at teardown (FOUND.md,
    2026-08-12).
    """
    from utils.audio_utils import AudioUtils
    bad = {"duration_s": 0.5, "loudness_dbfs": -50.0, "peak_dbfs": -3.0,
           "silence_ratio": 0.0, "clipping": False, "issues": ["too short"], "passed": False}
    monkeypatch.setattr(AudioUtils, "qc_check", staticmethod(lambda p: bad))


def _enqueue(client, headers):
    r = client.post("/api/synthesize", headers=headers, json={
        "text": "Chapter 1\n" + ("hi " * 30),
        "provider": "edge", "voice_id": "en-US-AvaNeural", "formats": ["mp3"],
    })
    return r.get_json()["task_id"]


def test_block_policy_holds_for_review(client, auth_headers, stub_pipeline, failing_qc, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "block")
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    from worker import process_one
    process_one("w")
    with session_scope() as s:
        assert s.get(m.Job, jid).status == m.JobStatus.needs_review


def test_warn_policy_still_succeeds(client, auth_headers, stub_pipeline, failing_qc, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "warn")
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    from worker import process_one
    process_one("w")
    with session_scope() as s:
        assert s.get(m.Job, jid).status == m.JobStatus.succeeded


def test_approve_promotes_to_succeeded(client, auth_headers, stub_pipeline, failing_qc, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "block")
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    from worker import process_one
    process_one("w")
    r = client.post(f"/api/jobs/{jid}/approve", headers=headers)
    assert r.status_code == 200 and r.get_json()["status"] == "succeeded"
    # Re-approving is a conflict.
    assert client.post(f"/api/jobs/{jid}/approve", headers=headers).status_code == 409


def test_reject_marks_failed(client, auth_headers, stub_pipeline, failing_qc, monkeypatch):
    monkeypatch.setenv("QC_POLICY", "block")
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    from worker import process_one
    process_one("w")
    r = client.post(f"/api/jobs/{jid}/reject", headers=headers, json={"reason": "bad audio"})
    assert r.status_code == 200 and r.get_json()["status"] == "failed"
