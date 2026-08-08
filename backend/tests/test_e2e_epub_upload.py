"""E2E: file upload text-extraction + EPUB export of a completed job.

Covers:
  - POST /api/upload  (txt happy path, bad extension, missing/empty file, auth)
  - GET  /api/jobs/<id>/export/epub  (succeeded job, redirect, guards, storage bytes)

Offline and deterministic: FakeSpeechProvider ("fake") + stub_pipeline; the
worker runs synchronously in-process via worker.process_one.
"""
import io

import pytest


# Chapter bodies must exceed the detector's _MIN_CHAPTER_BODY (500 chars) or
# "Chapter 2" is folded into chapter 1 instead of starting a new one
# (same trick as test_jobs.py::test_restart_resumes_completed_chapters).
TWO_CHAPTER_TEXT = (
    "Chapter 1\n" + ("The first chapter has plenty of words here. " * 15)
    + "\n\nChapter 2\n" + ("The second chapter also has plenty of words. " * 15)
)

UPLOAD_TEXT = "Chapter 1\n" + "Hello world. " * 50


@pytest.fixture()
def api(client):
    """Thin wrapper around the Flask test client with auth helpers."""

    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="epub-e2e@example.com", password="securepass123"):
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


def _run_job_to_succeeded(api, title="Epub Test Book", author="Epub Author"):
    """Golden-path recipe: enqueue via /api/synthesize then run the worker."""
    r = api.post("/api/synthesize", json={
        "text": TWO_CHAPTER_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
        "title": title,
        "author": author,
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]
    assert job_id

    from worker import process_one
    assert process_one(worker_id="epub-e2e-worker") is True, "worker found no job"

    r = api.get(f"/api/task/{job_id}")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "succeeded", (
        f"unexpected status: {body.get('status')} error={body.get('error')}"
    )
    assert body["chapters_count"] == 2
    return job_id


# --------------------------------------------------------------------------- #
# 1. Upload
# --------------------------------------------------------------------------- #
def test_upload_txt_extracts_text_and_chapters(engine, api):
    api.signup()

    r = api.post("/api/upload", data={
        "file": (io.BytesIO(UPLOAD_TEXT.encode("utf-8")), "book.txt"),
    })
    assert r.status_code == 200, r.get_json()
    body = r.get_json()

    # Exact response shape.
    assert set(body.keys()) == {"text", "characters_count", "words_count", "detected_chapters"}
    assert body["text"] == UPLOAD_TEXT
    assert body["characters_count"] == len(UPLOAD_TEXT)
    assert body["words_count"] == len(UPLOAD_TEXT.split())
    assert isinstance(body["detected_chapters"], list)
    assert len(body["detected_chapters"]) >= 1
    assert all(isinstance(t, str) and t for t in body["detected_chapters"])


def test_upload_rejects_disallowed_extension(engine, api):
    api.signup()

    r = api.post("/api/upload", data={
        "file": (io.BytesIO(b"MZ\x90\x00"), "malware.exe"),
    })
    assert r.status_code == 415, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert "Unsupported file type" in body["error"]
    assert ".exe" in body["error"]


def test_upload_missing_file_and_empty_filename(engine, api):
    api.signup()

    # No file part at all.
    r = api.post("/api/upload", data={"not_a_file": "x"})
    assert r.status_code == 400, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"] in ("No file provided", "No file selected")

    # File part present but with an empty filename (browser "no file chosen").
    r = api.post("/api/upload", data={"file": (io.BytesIO(b"data"), "")})
    assert r.status_code == 400, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"] in ("No file provided", "No file selected")


def test_upload_requires_auth(engine, client):
    r = client.post("/api/upload", data={
        "file": (io.BytesIO(b"Chapter 1\nHello."), "book.txt"),
    })
    assert r.status_code == 401
    body = r.get_json()
    assert "error" in body and body["error"]


# --------------------------------------------------------------------------- #
# 2 + 4. EPUB export from a succeeded job + stored-object sanity
# --------------------------------------------------------------------------- #
def test_epub_export_from_succeeded_job(engine, stub_pipeline, api):
    body = api.signup()
    org_id = body["organization"]["id"]

    job_id = _run_job_to_succeeded(api)

    # JSON mode: signed URL + size.
    r = api.get(f"/api/jobs/{job_id}/export/epub")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"success", "url", "expires_in", "size"}
    assert body["success"] is True
    assert isinstance(body["url"], str) and body["url"]
    assert isinstance(body["size"], int) and body["size"] > 0
    assert isinstance(body["expires_in"], int) and body["expires_in"] > 0

    # 4. Content sanity: the stored object is a real zip container (EPUB).
    # (Checked before the redirect call: each GET regenerates and re-uploads
    # the object, and EPUB zip bytes are not byte-identical across builds.)
    from storage import get_storage
    epub_bytes = get_storage().get_bytes(f"epub/{org_id}/{job_id}.epub")
    assert epub_bytes.startswith(b"PK"), "EPUB must be a zip archive (PK magic)"
    assert len(epub_bytes) == body["size"]

    # Redirect mode.
    r = api.get(f"/api/jobs/{job_id}/export/epub?redirect=1")
    assert r.status_code == 302
    assert r.headers.get("Location")


# --------------------------------------------------------------------------- #
# 3. EPUB guards
# --------------------------------------------------------------------------- #
def test_epub_export_queued_job_conflicts(engine, stub_pipeline, api):
    api.signup("queued-epub@example.com", "pass1234567")

    r = api.post("/api/synthesize", json={
        "text": TWO_CHAPTER_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
        "title": "Never Processed",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    # Worker never ran: the job is still queued -> 409 Conflict.
    r = api.get(f"/api/jobs/{job_id}/export/epub")
    assert r.status_code == 409, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"] == "Job must be succeeded to export"


def test_epub_export_cross_org_denied(engine, stub_pipeline, api):
    """_get_owned_job raises AuthzError for foreign (and unknown) jobs, and the
    app-level errorhandler maps that to exactly 403 — never a 404 that would
    leak or deny differently."""
    api.signup("epub-owner@example.com", "pass1234567")
    job_id = _run_job_to_succeeded(api, title="Owner Book")

    # Second org via a reloaded app module (fresh client, same per-test DB).
    import importlib
    import app as appmod
    importlib.reload(appmod)
    appmod.app.config.update(TESTING=True)
    other_client = appmod.app.test_client()

    r = other_client.post("/api/auth/signup",
                          json={"email": "epub-other@example.com", "password": "pass1234567"})
    assert r.status_code == 200
    other_headers = {"Authorization": f"Bearer {r.get_json()['token']}"}

    r = other_client.get(f"/api/jobs/{job_id}/export/epub", headers=other_headers)
    assert r.status_code == 403, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert body["error"] == "Not a member of that organization"

    # Nonexistent job id is indistinguishable: also 403 (no existence leak).
    r = other_client.get("/api/jobs/does-not-exist/export/epub", headers=other_headers)
    assert r.status_code == 403, r.get_json()
    assert r.get_json() == {"error": "Job not found"}
