"""Supabase Auth mode: token verification and just-in-time provisioning."""
import time

import jwt
import pytest

SECRET = "supabase-unit-secret"


def _sb_token(sub="sb-user-1", email="renee@mangu.com", exp_delta=3600, aud="authenticated", secret=SECRET):
    return jwt.encode(
        {"sub": sub, "email": email, "aud": aud, "exp": int(time.time()) + exp_delta,
         "user_metadata": {"full_name": "Renee M"}},
        secret, algorithm="HS256",
    )


@pytest.fixture()
def supabase_client(engine, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    import importlib
    import app as appmod
    importlib.reload(appmod)
    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


def test_valid_supabase_token_provisions_user(supabase_client):
    r = supabase_client.get("/api/auth/me", headers={"Authorization": f"Bearer {_sb_token()}"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == "renee@mangu.com"
    assert body["organization"]["name"]  # personal workspace created


def test_provisioning_is_idempotent(supabase_client):
    tok = _sb_token()
    h = {"Authorization": f"Bearer {tok}"}
    supabase_client.get("/api/auth/me", headers=h)
    r2 = supabase_client.get("/api/auth/me", headers=h)
    assert r2.status_code == 200
    # Same user id both times (the Supabase subject).
    assert r2.get_json()["user"]["id"] == "sb-user-1"


def test_expired_token_rejected(supabase_client):
    tok = _sb_token(exp_delta=-10)
    assert supabase_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_wrong_signature_rejected(supabase_client):
    tok = _sb_token(secret="not-the-secret")
    assert supabase_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_wrong_audience_rejected(supabase_client):
    tok = _sb_token(aud="some-other-aud")
    assert supabase_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_missing_token_rejected(supabase_client):
    assert supabase_client.get("/api/auth/me").status_code == 401
