"""API-level quota (402) and rate limit (429), plus the usage endpoint."""
from db import models as m
from db.session import session_scope


def _body(provider="edge", voice="en-US-AvaNeural", chars=90):
    return {"text": "Chapter 1\n" + ("hi " * (chars // 3)),
            "provider": provider, "voice_id": voice, "formats": ["mp3"]}


def test_rate_limit_429(client, auth_headers, monkeypatch):
    monkeypatch.setenv("SYNTHESIZE_RATE_LIMIT", "3")
    monkeypatch.setenv("SYNTHESIZE_RATE_WINDOW_SECONDS", "3600")
    import importlib
    import app as appmod
    importlib.reload(appmod)
    c = appmod.app.test_client()
    r = c.post("/api/auth/signup", json={"email": "rl@x.com", "password": "password123"})
    h = {"Authorization": f"Bearer {r.get_json()['token']}"}
    codes = [c.post("/api/synthesize", headers=h, json=_body()).status_code for _ in range(5)]
    assert codes.count(200) == 3
    assert codes.count(429) == 2


def test_quota_402_for_paid_provider(client, auth_headers, monkeypatch):
    # Make polly available so we can exercise the paid path.
    from services.providers.polly_provider import PollyProvider
    monkeypatch.setattr(PollyProvider, "is_available", lambda self: True)
    monkeypatch.setattr(PollyProvider, "list_voices",
                        lambda self, language=None: [{"id": "Joanna", "name": "Joanna",
                                                      "language": "en-US", "gender": "Female", "neural": True}])
    headers, org_id = auth_headers("q@x.com")
    with session_scope() as s:
        s.get(m.Organization, org_id).monthly_char_quota = 50
    r = client.post("/api/synthesize", headers=headers,
                    json={"text": "x" * 200, "provider": "polly", "voice_id": "Joanna", "formats": ["mp3"]})
    assert r.status_code == 402
    assert r.get_json()["quota"] == 50


def test_usage_endpoint(client, auth_headers):
    headers, _ = auth_headers("u@x.com")
    r = client.get("/api/usage", headers=headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body["characters"] == 0 and "period" in body
