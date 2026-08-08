"""Golden-path end-to-end test (P0.8).

Exercises the full HTTP API surface with a real DB and the FakeSpeechProvider:
  signup → upload text → synthesize → poll to success → download URL

No ffmpeg, no network, no AWS credentials required. Uses:
  - FakeSpeechProvider (provider="fake") for deterministic offline synthesis
  - stub_pipeline fixture for audio assembly stubs
  - Flask test client for HTTP calls
  - Real SQLAlchemy sessions (SQLite in CI, Postgres when DATABASE_URL is set)
"""
import pytest

from db.session import session_scope


BOOK_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "It was the best of times, it was the worst of times. " * 10
    + "\n\nChapter 2: The Middle\n\n"
    "Call me Ishmael. " * 15
)


@pytest.fixture()
def api(client):
    """Thin wrapper around the Flask test client with JSON helpers."""

    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="e2e@example.com", password="securepass123"):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            self._token = body["token"]
            return body

        @property
        def _headers(self):
            assert self._token, "call signup() first"
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path, **kw):
            return self._c.get(path, headers=self._headers, **kw)

        def post(self, path, **kw):
            return self._c.post(path, headers=self._headers, **kw)

    return _API(client)


def test_golden_path_signup_synthesize_download(engine, stub_pipeline, api):
    """Full happy path: signup → synthesize → poll → download URL check."""

    # 1. Sign up
    body = api.signup()
    org_id = body["organization"]["id"]
    assert body["user"]["email"] == "e2e@example.com"

    # 2. Upload / paste text (direct synthesize with inline text)
    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
        "title": "E2E Test Book",
        "author": "Test Author",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]
    assert job_id

    # 3. Run the worker synchronously (same process, no thread/subprocess needed)
    from worker import process_one
    did_work = process_one(worker_id="e2e-worker")
    assert did_work, "worker found no job to process"

    # 4. Poll: job must be succeeded
    r = api.get(f"/api/task/{job_id}")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "succeeded", f"unexpected status: {body.get('status')} error={body.get('error')}"
    assert body["progress"] == 100
    assert body["chapters_count"] >= 1

    # 5. Download URL endpoint returns a signed URL (not the bytes directly)
    r = api.get(f"/api/download/{job_id}?format=mp3")
    assert r.status_code == 200, r.get_json()
    dl_body = r.get_json()
    assert "url" in dl_body
    assert dl_body["url"]  # non-empty


def test_golden_path_job_list_is_org_scoped(engine, stub_pipeline, api):
    """Jobs are scoped to the creating org — another org cannot see them."""

    body = api.signup("owner@example.com", "pass1234567")
    assert body["user"]["email"] == "owner@example.com"

    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    # A different org cannot see this job.
    import importlib
    import app as appmod
    importlib.reload(appmod)
    appmod.app.config.update(TESTING=True)
    other_client = appmod.app.test_client()

    r2 = other_client.post("/api/auth/signup", json={"email": "other@example.com", "password": "pass1234567"})
    assert r2.status_code == 200
    other_token = r2.get_json()["token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    r3 = other_client.get(f"/api/task/{job_id}", headers=other_headers)
    assert r3.status_code in (403, 404), (
        f"cross-org access should be denied, got {r3.status_code}: {r3.get_json()}"
    )


def test_golden_path_cancel(engine, stub_pipeline, api):
    """Enqueue a job and cancel it before the worker picks it up."""

    api.signup("cancel@example.com", "pass1234567")

    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    # Cancel while still queued
    r = api.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200, r.get_json()

    r = api.get(f"/api/task/{job_id}")
    assert r.status_code == 200
    assert r.get_json()["status"] == "canceled"
