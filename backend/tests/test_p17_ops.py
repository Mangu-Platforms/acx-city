"""P1.7: observational ops endpoints backing the dashboard pipeline page."""
import pytest


@pytest.fixture()
def api(client):
    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="p17@example.com", password="securepass123"):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            self._token = r.get_json()["token"]

        @property
        def headers(self):
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path):
            return self._c.get(path, headers=self.headers)

        def post(self, path, **kw):
            return self._c.post(path, headers=self.headers, **kw)

    return _API(client)


BOOK_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "It was the best of times, it was the worst of times. " * 10
)


def test_ops_pipeline_shape_and_org_scoping(engine, stub_pipeline, api, client):
    api.signup()
    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT, "provider": "fake", "voice_id": "fake-a",
        "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    from worker import process_one
    assert process_one("p17-worker") is True

    r = api.get("/api/ops/pipeline")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    for key in ("queue", "workers", "recent_jobs", "failed_chapters",
                "qc_failures", "recent_exports", "cache_hit_rate",
                "avg_job_duration_s", "providers", "storage"):
        assert key in body, f"ops payload missing {key}"
    assert body["queue"]["queued"] == 0
    assert body["storage"]["ok"] is True
    assert any(j["job_id"] == job_id for j in body["recent_jobs"])
    assert any(e["job_id"] == job_id and "mp3" in e["formats"]
               for e in body["recent_exports"])
    assert any(p["name"] == "fake" and p["available"] for p in body["providers"])

    # Stage timeline exists and is ordered.
    r = api.get(f"/api/jobs/{job_id}/stages")
    assert r.status_code == 200
    stages = r.get_json()["stages"]
    assert stages, "a completed job must have stage records"
    assert stages == sorted(stages, key=lambda s: (s["chapter_index"], s["completed_at"]))
    assert any(s["stage"] == "upload" for s in stages)

    # Org scoping: another org sees none of this org's jobs.
    r2 = client.post("/api/auth/signup", json={
        "email": "p17-other@example.com", "password": "pass1234567"})
    other_headers = {"Authorization": f"Bearer {r2.get_json()['token']}"}
    r3 = client.get("/api/ops/pipeline", headers=other_headers)
    assert r3.status_code == 200
    other = r3.get_json()
    assert all(j["job_id"] != job_id for j in other["recent_jobs"])
    assert other["recent_exports"] == []
    r4 = client.get(f"/api/jobs/{job_id}/stages", headers=other_headers)
    assert r4.status_code in (403, 404)

    # Unauthenticated → 401.
    assert client.get("/api/ops/pipeline").status_code == 401
