"""Retention & lifecycle: asset deletion, sweep, and the delete endpoint."""
from datetime import timedelta

from db.base import utcnow
from db import models as m
from db.session import session_scope
from storage import get_storage


def _seed_succeeded_job(session, storage, updated_days_ago=0):
    org = m.Organization(name="O")
    session.add(org)
    session.flush()
    proj = m.Project(organization_id=org.id, title="B", source_text="x")
    session.add(proj)
    session.flush()
    key = f"org/{org.id}/jobs/test/audiobook.mp3"
    storage.put_bytes(key, b"ID3audio")
    job = m.Job(
        organization_id=org.id, project_id=proj.id, provider="edge", voice_id="v",
        status=m.JobStatus.succeeded, output_mp3_key=key,
        updated_at=utcnow() - timedelta(days=updated_days_ago),
    )
    session.add(job)
    session.flush()
    return job, key


def test_delete_job_assets_removes_objects(engine):
    from jobs.retention import delete_job_assets
    storage = get_storage()
    with session_scope() as s:
        job, key = _seed_succeeded_job(s, storage)
        assert storage.exists(key)
        removed = delete_job_assets(s, job)
        assert removed == 1
        assert not storage.exists(key)
        assert job.output_mp3_key is None


def test_sweep_respects_retention_window(engine):
    from jobs.retention import sweep_expired
    storage = get_storage()
    with session_scope() as s:
        fresh, fresh_key = _seed_succeeded_job(s, storage, updated_days_ago=1)
        old, old_key = _seed_succeeded_job(s, storage, updated_days_ago=40)
        # Set a 30-day retention on both orgs.
        for j in (fresh, old):
            s.get(m.Organization, j.organization_id).retention_days = 30
    with session_scope() as s:
        summary = sweep_expired(s, delete_rows=False)
    assert summary["jobs_swept"] == 1  # only the 40-day-old one
    assert storage.exists(fresh_key)
    assert not storage.exists(old_key)


def test_delete_endpoint(client, auth_headers, stub_pipeline):
    headers, _ = auth_headers("owner@x.com")
    r = client.post("/api/synthesize", headers=headers, json={
        "text": "Chapter 1\n" + ("hi " * 30),
        "provider": "edge", "voice_id": "en-US-AvaNeural", "formats": ["mp3"],
    })
    jid = r.get_json()["task_id"]
    from worker import process_one
    process_one("w")
    # Delete removes the row and its assets.
    r = client.delete(f"/api/jobs/{jid}", headers=headers)
    assert r.status_code == 200 and r.get_json()["deleted"] is True
    assert client.get(f"/api/task/{jid}", headers=headers).status_code == 403  # gone
