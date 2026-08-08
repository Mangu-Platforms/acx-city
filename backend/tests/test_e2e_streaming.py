"""End-to-end tests for the streaming endpoints (services/streaming.py).

Covers:
  - GET /api/stream/<job_id>/chapter/<n>
      * 302 redirect to a signed URL when the chapter has a storage audio_key
      * local-file fallback (audio_key NULL): full body, Range requests, 416
      * authz / state errors: cross-org 404, queued 409, missing chapter 404
  - POST /api/stream/preview
      * happy path streams audio/mpeg bytes (offline via class-level patch)
      * validation: missing text / voice_id, oversized text, unauthenticated

Deterministic and offline: jobs run with provider="fake" (FakeSpeechProvider)
under the stub_pipeline fixture; the preview path additionally patches
EdgeProvider.synthesize_with_options because registry.default() selects edge
and its real implementation would hit the network.
"""
import os

import pytest
from sqlalchemy import select

from db.session import session_scope


BOOK_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "It was the best of times, it was the worst of times. " * 10
    + "\n\nChapter 2: The Middle\n\n"
    "Call me Ishmael. " * 15
)

LOCAL_BYTES = b"ID3localfile"  # 12 bytes; deterministic local-fallback content


@pytest.fixture()
def api(client):
    """Thin wrapper around the Flask test client with JSON helpers."""

    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="stream@example.com", password="securepass123"):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            self._token = body["token"]
            return body

        @property
        def _headers(self):
            assert self._token, "call signup() first"
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path, extra_headers=None, **kw):
            headers = {**self._headers, **(extra_headers or {})}
            return self._c.get(path, headers=headers, **kw)

        def post(self, path, **kw):
            return self._c.post(path, headers=self._headers, **kw)

    return _API(client)


def _enqueue_job(api):
    """POST /api/synthesize with the offline fake provider; return job_id."""
    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3"],
        "title": "Streaming E2E Book",
        "author": "Test Author",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]
    assert job_id
    return job_id


def _run_job_to_success(api, job_id):
    """Process the queued job synchronously and assert it succeeded."""
    from worker import process_one
    did_work = process_one(worker_id="e2e-stream-worker")
    assert did_work, "worker found no job to process"

    r = api.get(f"/api/task/{job_id}")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "succeeded", (
        f"unexpected status: {body.get('status')} error={body.get('error')}"
    )


def _chapter_row_audio_key(job_id, index=0):
    """Return (audio_key, status_name) for a chapter row straight from the DB."""
    from db.models import ChapterResult

    with session_scope() as session:
        row = session.execute(
            select(ChapterResult).where(
                ChapterResult.job_id == job_id,
                ChapterResult.index == index,
            )
        ).scalar_one()
        return row.audio_key, row.status.name


# ---------------------------------------------------------------------------
# 1. Storage-backed chapter -> 302 signed URL redirect
# ---------------------------------------------------------------------------

def test_stream_chapter_redirects_to_signed_url(engine, stub_pipeline, api):
    api.signup()
    job_id = _enqueue_job(api)
    _run_job_to_success(api, job_id)

    # The stubbed pipeline uploads chapter audio and records audio_key.
    audio_key, status_name = _chapter_row_audio_key(job_id, 0)
    assert status_name == "done"

    if audio_key is None:
        # Defensive fallback: place bytes in storage and record the key so the
        # redirect branch is still exercised deterministically.
        from db.models import ChapterResult
        from storage import get_storage

        audio_key = f"org/test/jobs/{job_id}/chapters/000.mp3"
        get_storage().put_bytes(audio_key, b"ID3storagebytes", content_type="audio/mpeg")
        with session_scope() as session:
            row = session.execute(
                select(ChapterResult).where(
                    ChapterResult.job_id == job_id,
                    ChapterResult.index == 0,
                )
            ).scalar_one()
            row.audio_key = audio_key

    r = api.get(f"/api/stream/{job_id}/chapter/0")
    assert r.status_code == 302, (r.status_code, r.get_data(as_text=True)[:200])

    location = r.headers.get("Location")
    assert location, "302 must carry a Location header"
    # Local storage backend signs an app-served URL with expiry + HMAC.
    assert "/api/files/" in location
    assert "expires=" in location
    assert "sig=" in location
    assert "name=chapter_000.mp3" in location


# ---------------------------------------------------------------------------
# 2. Local-file fallback: full body, Range requests, 416
# ---------------------------------------------------------------------------

def test_stream_chapter_local_file_fallback_and_ranges(engine, stub_pipeline, api):
    api.signup()
    job_id = _enqueue_job(api)
    _run_job_to_success(api, job_id)

    # Force the local-disk branch: clear the storage pointer.
    from db.models import ChapterResult

    with session_scope() as session:
        row = session.execute(
            select(ChapterResult).where(
                ChapterResult.job_id == job_id,
                ChapterResult.index == 0,
            )
        ).scalar_one()
        row.audio_key = None
        row.audio_sha256 = None

    # Write known bytes where the streamer looks for local chapters.
    chapter_dir = os.path.join(os.environ["OUTPUT_FOLDER"], job_id)
    os.makedirs(chapter_dir, exist_ok=True)
    audio_path = os.path.join(chapter_dir, "chapter_000.mp3")
    with open(audio_path, "wb") as f:
        f.write(LOCAL_BYTES)

    size = len(LOCAL_BYTES)  # 12

    # -- full-body request ---------------------------------------------------
    r = api.get(f"/api/stream/{job_id}/chapter/0")
    assert r.status_code == 200
    assert r.mimetype == "audio/mpeg"
    assert r.headers.get("Accept-Ranges") == "bytes"
    assert r.headers.get("Content-Length") == str(size)
    assert r.headers.get("Content-Disposition") == 'inline; filename="chapter_000.mp3"'
    assert r.data == LOCAL_BYTES

    # -- partial content -----------------------------------------------------
    r = api.get(f"/api/stream/{job_id}/chapter/0",
                extra_headers={"Range": "bytes=3-6"})
    assert r.status_code == 206
    assert r.mimetype == "audio/mpeg"
    assert r.headers.get("Content-Range") == f"bytes 3-6/{size}"
    assert r.headers.get("Content-Length") == "4"
    assert r.data == LOCAL_BYTES[3:7]
    assert len(r.data) == 4

    # -- unsatisfiable range -------------------------------------------------
    r = api.get(f"/api/stream/{job_id}/chapter/0",
                extra_headers={"Range": "bytes=999999-"})
    assert r.status_code == 416
    assert r.headers.get("Content-Range") == f"bytes */{size}"
    assert r.data == b""


# ---------------------------------------------------------------------------
# 3. Authorization and job/chapter state errors
# ---------------------------------------------------------------------------

def test_stream_chapter_authz_and_state_errors(engine, stub_pipeline, api):
    api.signup("owner-stream@example.com", "pass1234567")
    job_id = _enqueue_job(api)

    # Queued (unprocessed) job -> 409 conflict.
    r = api.get(f"/api/stream/{job_id}/chapter/0")
    assert r.status_code == 409
    assert r.get_json() == {"error": "Job is not completed yet"}

    _run_job_to_success(api, job_id)

    # Nonexistent chapter index on a succeeded job -> 404.
    r = api.get(f"/api/stream/{job_id}/chapter/99")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Chapter not found"}

    # Cross-org access -> 404 (job invisible to another organization).
    import importlib
    import app as appmod
    importlib.reload(appmod)
    appmod.app.config.update(TESTING=True)
    other_client = appmod.app.test_client()

    r2 = other_client.post("/api/auth/signup", json={
        "email": "other-stream@example.com", "password": "pass1234567",
    })
    assert r2.status_code == 200, r2.get_json()
    other_headers = {"Authorization": f"Bearer {r2.get_json()['token']}"}

    r3 = other_client.get(f"/api/stream/{job_id}/chapter/0", headers=other_headers)
    assert r3.status_code == 404, (r3.status_code, r3.get_json())
    assert r3.get_json() == {"error": "Job not found"}


# ---------------------------------------------------------------------------
# 4. Instant preview happy path (offline)
# ---------------------------------------------------------------------------

def test_stream_preview_returns_mpeg_bytes(engine, stub_pipeline, api, monkeypatch):
    """Preview synthesizes via registry.default() (edge under stub_pipeline).

    stub_pipeline patches EdgeProvider.is_available/synthesize at class level,
    but the preview path calls synthesize_with_options, which on EdgeProvider
    is real network code — patch it too so the test stays offline.
    """
    from services.providers.edge_provider import EdgeProvider

    monkeypatch.setattr(
        EdgeProvider,
        "synthesize_with_options",
        lambda self, text, voice_id, engine="neural", **kw: (
            b"ID3preview" + text[:8].encode()
        ),
    )

    api.signup()
    r = api.post("/api/stream/preview", json={
        "text": "Hello world",
        "voice_id": "en-US-AriaNeural",
    })
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    assert r.mimetype == "audio/mpeg"
    assert r.headers.get("Cache-Control") == "no-store"
    assert r.data.startswith(b"ID3")
    # Deterministic body from the patched provider: text passes through intact.
    assert r.data == b"ID3previewHello wo"


# ---------------------------------------------------------------------------
# 5. Preview validation
# ---------------------------------------------------------------------------

def test_stream_preview_validation(engine, stub_pipeline, api, client):
    api.signup()

    # Missing text -> 400
    r = api.post("/api/stream/preview", json={"voice_id": "en-US-AriaNeural"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "text is required"}

    # Missing voice_id -> 400
    r = api.post("/api/stream/preview", json={"text": "Hello world"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "voice_id is required"}

    # Text over the 2000-char limit -> 400
    r = api.post("/api/stream/preview", json={
        "text": "a" * 2001,
        "voice_id": "en-US-AriaNeural",
    })
    assert r.status_code == 400
    assert r.get_json() == {"error": "text exceeds 2000 character limit"}

    # Unauthenticated -> 401
    r = client.post("/api/stream/preview", json={
        "text": "Hello world",
        "voice_id": "en-US-AriaNeural",
    })
    assert r.status_code == 401
    body = r.get_json()
    assert isinstance(body, dict) and "error" in body
