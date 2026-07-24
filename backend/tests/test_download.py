"""Signed-URL download flow: the API returns a signed URL, the URL serves the
file, and tampered/cross-org access is rejected."""


def _enqueue(client, headers):
    r = client.post("/api/synthesize", headers=headers, json={
        "text": "Chapter 1\n" + ("Hello world. " * 30),
        "provider": "edge", "voice_id": "en-US-AvaNeural", "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    return r.get_json()["task_id"]


def _run_worker(monkeypatch):
    from worker import process_one
    return process_one("test-worker")


def test_download_returns_working_signed_url(client, auth_headers, stub_pipeline):
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    _run_worker(None)

    # 1) The download endpoint returns a signed URL (not the bytes).
    r = client.get(f"/api/download/{jid}?format=mp3", headers=headers)
    assert r.status_code == 200
    url = r.get_json()["url"]
    assert "sig=" in url and "expires=" in url

    # 2) Following the signed URL serves the file (no auth header needed — the
    #    signature is the grant).
    r2 = client.get(url)
    assert r2.status_code == 200
    assert len(r2.data) > 0


def test_tampered_signed_url_rejected(client, auth_headers, stub_pipeline):
    headers, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, headers)
    _run_worker(None)
    url = client.get(f"/api/download/{jid}?format=mp3", headers=headers).get_json()["url"]
    # Flip the signature.
    tampered = url.replace("sig=", "sig=deadbeef")
    assert client.get(tampered).status_code in (403, 400)


def test_cross_org_cannot_get_download_url(client, auth_headers, stub_pipeline):
    owner_h, _ = auth_headers("owner@x.com")
    jid = _enqueue(client, owner_h)
    _run_worker(None)
    attacker_h, _ = auth_headers("attacker@evil.com")
    assert client.get(f"/api/download/{jid}?format=mp3", headers=attacker_h).status_code == 403
