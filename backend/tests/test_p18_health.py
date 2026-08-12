"""P1.8: liveness/readiness split + worker heartbeat surfacing.

Gate: killing the worker flips /health/ready to workers: stale within 90s —
modeled by aging the heartbeat row past the 90s threshold. Provider outages
degrade, never crash. Hard dependency failures (storage) are 503 unready;
liveness never touches a dependency.
"""
from datetime import timedelta

import pytest

from db.base import utcnow
from db.session import session_scope
from db import models as m


BOOK_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "It was the best of times, it was the worst of times. " * 10
)


def _signup_and_run_job(client):
    r = client.post("/api/auth/signup", json={
        "email": "p18@example.com", "password": "securepass123"})
    headers = {"Authorization": f"Bearer {r.get_json()['token']}"}
    r = client.post("/api/synthesize", headers=headers, json={
        "text": BOOK_TEXT, "provider": "fake", "voice_id": "fake-a",
        "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    from worker import process_one
    assert process_one("p18-worker") is True


def test_live_touches_no_dependencies(engine, client, monkeypatch):
    # Break storage AND the DB layer: liveness must not notice.
    from storage.local import LocalStorage

    def _explode(*a, **k):
        raise RuntimeError("storage down")

    monkeypatch.setattr(LocalStorage, "put_bytes", _explode)
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.get_json() == {"status": "alive"}


def test_ready_with_fresh_worker(engine, client, stub_pipeline):
    _signup_and_run_job(client)
    r = client.get("/health/ready")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    checks = body["checks"]
    assert checks["database"] == "ok"
    assert checks["storage"] == "ok"
    assert checks["workers"] == "ok"
    assert checks["worker_age_s"] <= 90
    assert checks["providers"] == "ok" and "fake" in checks["providers_available"]
    # create_all test DB is unstamped → degraded, not unready.
    assert checks["migrations"] == "unstamped"
    assert body["status"] == "degraded"


def test_dead_worker_flips_ready_to_stale_within_90s(engine, client, stub_pipeline):
    _signup_and_run_job(client)

    # Simulate the worker dying: its heartbeat row ages past the threshold.
    with session_scope() as s:
        hb = s.execute(
            m.WorkerHeartbeat.__table__.select()
        ).first()
        assert hb is not None
        s.execute(
            m.WorkerHeartbeat.__table__.update().values(
                last_seen=utcnow() - timedelta(seconds=120))
        )

    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.get_json()
    assert body["checks"]["workers"] == "stale"
    assert body["checks"]["worker_age_s"] > 90
    assert body["status"] == "degraded"


def test_no_worker_yet_is_degraded_not_unready(engine, client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.get_json()["checks"]["workers"] == "none"
    assert r.get_json()["status"] == "degraded"


def test_provider_outage_degrades_never_crashes(engine, client, monkeypatch):
    import app as appmod

    for provider in appmod.registry.describe_all():
        prov = appmod.registry.get(provider["name"])
        monkeypatch.setattr(prov, "is_available", lambda: False)

    r = client.get("/health/ready")
    assert r.status_code == 200, "provider outage must degrade, not fail"
    body = r.get_json()
    assert body["checks"]["providers"] == "none_available"
    assert body["status"] == "degraded"


def test_storage_failure_is_unready_503(engine, client, monkeypatch):
    from storage.local import LocalStorage

    def _explode(self, *a, **k):
        raise RuntimeError("storage down")

    monkeypatch.setattr(LocalStorage, "put_bytes", _explode)
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.get_json()
    assert body["status"] == "unready"
    assert body["checks"]["storage"] == "unreachable"
