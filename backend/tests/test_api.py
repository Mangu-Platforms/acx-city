"""Public + auth-gated API surface tests."""


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert data["database"] == "ok"
    assert any(p["name"] == "edge" for p in data["providers"])


def test_providers_public(client):
    res = client.get("/api/providers")
    assert res.status_code == 200
    names = {p["name"] for p in res.get_json()}
    assert {"edge", "polly"} <= names


def test_synthesize_requires_auth(client):
    assert client.post("/api/synthesize", json={"text": "hi"}).status_code == 401


def test_synthesize_requires_text(client, auth_headers):
    headers, _ = auth_headers()
    res = client.post("/api/synthesize", headers=headers, json={})
    assert res.status_code == 400


def test_signup_login_flow(client):
    r = client.post("/api/auth/signup", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 200
    assert "token" in r.get_json()
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert r.status_code == 401


def test_duplicate_signup_rejected(client):
    client.post("/api/auth/signup", json={"email": "dup@b.com", "password": "password123"})
    r = client.post("/api/auth/signup", json={"email": "dup@b.com", "password": "password123"})
    assert r.status_code == 400
