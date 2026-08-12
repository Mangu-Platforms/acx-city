"""End-to-end tests for the streaming endpoints (services/streaming.py, P1.4).

Covers:
  - GET /api/stream/<job_id>/chapter/<n>
      * 302 redirect to a signed URL when the chapter has a storage audio_key
      * audio_key is the ONLY resolution path: a chapter without a durable
        artifact is 409, never a local-disk guess
      * real-audio round trip: follow the redirect, decode, seek via Range
      * authz / state errors: cross-org 404, queued 409, missing chapter 404
  - POST /api/stream/preview
      * returns a signed URL to a stored, decodable, content-addressed
        preview; identical requests reuse it (cached=true)
      * validation: missing text / voice_id, oversized text, unauthenticated

Real-audio tests run without stub_pipeline against FakeSpeechProvider's
genuine MP3 output; state-machine tests keep the fast stubs.
"""
import io
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


def _follow(api, url):
    """GET a signed URL through the test client (strip scheme+host)."""
    path_and_query = url.split("://", 1)[-1].split("/", 1)[1]
    return api.get("/" + path_and_query)


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


# ---------------------------------------------------------------------------
# 2. audio_key is the only path: no artifact → 409, never a local-disk guess
# ---------------------------------------------------------------------------

def test_stream_chapter_without_artifact_is_conflict(engine, stub_pipeline, api):
    api.signup()
    job_id = _enqueue_job(api)
    _run_job_to_success(api, job_id)

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

    r = api.get(f"/api/stream/{job_id}/chapter/0")
    assert r.status_code == 409
    assert "durable audio artifact" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# 2b. Real audio round trip: follow the redirect, decode, seek via Range
# ---------------------------------------------------------------------------

def test_stream_chapter_real_audio_with_ranges(engine, api):
    from pydub import AudioSegment

    api.signup("stream-real@example.com")
    job_id = _enqueue_job(api)
    _run_job_to_success(api, job_id)

    r = api.get(f"/api/stream/{job_id}/chapter/0")
    assert r.status_code == 302
    location = r.headers["Location"]

    # Full body: inline (not attachment), decodable, seekable.
    full = _follow(api, location)
    assert full.status_code == 200
    assert full.mimetype == "audio/mpeg"
    disposition = full.headers.get("Content-Disposition", "")
    assert "attachment" not in disposition, "streaming must serve inline"
    assert full.headers.get("Accept-Ranges") == "bytes"
    seg = AudioSegment.from_file(io.BytesIO(full.data), format="mp3")
    assert len(seg) > 1000 and seg.dBFS > -45

    # Partial content: a seek returns exactly the requested slice.
    part = api.get("/" + location.split("://", 1)[-1].split("/", 1)[1],
                   extra_headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert part.headers.get("Content-Range") == f"bytes 0-99/{len(full.data)}"
    assert part.data == full.data[:100]

    # Unsatisfiable range.
    bad = api.get("/" + location.split("://", 1)[-1].split("/", 1)[1],
                  extra_headers={"Range": f"bytes={len(full.data) + 10}-"})
    assert bad.status_code == 416


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
# 4. Instant preview: signed URL to a stored, decodable, deduplicated artifact
# ---------------------------------------------------------------------------

def test_stream_preview_returns_signed_url_to_real_audio(engine, api):
    from pydub import AudioSegment

    api.signup("preview-real@example.com")
    payload = {
        "text": "Hello there, and welcome to the audition.",
        "voice_id": "fake-a",
        "provider": "fake",
    }
    r = api.post("/api/stream/preview", json=payload)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    body = r.get_json()
    assert body["url"] and body["cached"] is False
    assert body["provider"] == "fake"

    fetched = _follow(api, body["url"])
    assert fetched.status_code == 200
    seg = AudioSegment.from_file(io.BytesIO(fetched.data), format="mp3")
    assert len(seg) > 300 and seg.dBFS > -45, "preview must be real audible audio"

    # Content-addressed: an identical request reuses the stored artifact.
    r2 = api.post("/api/stream/preview", json=payload)
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["cached"] is True
    assert body2["url"].split("?")[0] == body["url"].split("?")[0]


def test_stream_preview_unavailable_provider_is_503(engine, api):
    api.signup("preview-unavail@example.com")
    r = api.post("/api/stream/preview", json={
        "text": "Hello world",
        "voice_id": "Joanna",
        "provider": "polly",  # no AWS credentials in tests → unavailable
    })
    assert r.status_code == 503
    assert "unavailable" in r.get_json()["error"]


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
