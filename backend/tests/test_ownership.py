"""Ownership / multi-tenant isolation: a job id must never authorize access."""


def _enqueue(client, headers):
    r = client.post("/api/synthesize", headers=headers, json={
        "text": "Chapter 1\n" + ("Hello world. " * 30),
        "provider": "edge", "voice_id": "en-US-AvaNeural", "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    return r.get_json()["task_id"]


def test_owner_can_read_job(client, auth_headers):
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    r = client.get(f"/api/task/{jid}", headers=headers)
    assert r.status_code == 200
    assert r.get_json()["status"] == "queued"


def test_cross_org_cannot_read_job(client, auth_headers):
    owner_h, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, owner_h)
    attacker_h, _ = auth_headers("attacker@evil.com")
    # 403 (not 404) — we don't even confirm the job exists to a non-member.
    assert client.get(f"/api/task/{jid}", headers=attacker_h).status_code == 403


def test_cross_org_cannot_download_or_cancel(client, auth_headers):
    owner_h, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, owner_h)
    attacker_h, _ = auth_headers("attacker@evil.com")
    assert client.get(f"/api/download/{jid}", headers=attacker_h).status_code == 403
    assert client.post(f"/api/jobs/{jid}/cancel", headers=attacker_h).status_code == 403


def test_list_jobs_scoped_to_org(client, auth_headers):
    owner_h, _ = auth_headers("owner@x.com")
    _enqueue(client, owner_h)
    _enqueue(client, owner_h)
    other_h, _ = auth_headers("other@x.com")
    _enqueue(client, other_h)
    assert len(client.get("/api/jobs", headers=owner_h).get_json()) == 2
    assert len(client.get("/api/jobs", headers=other_h).get_json()) == 1
