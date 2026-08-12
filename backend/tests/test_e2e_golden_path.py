"""Golden-path end-to-end tests (P0.8).

Exercise the full HTTP API surface with a real DB and the FakeSpeechProvider:
  signup → upload text → synthesize → poll to success → download URL

Two tiers:
  - Stubbed tests (stub_pipeline fixture): fast state-machine coverage; audio
    assembly/QC are monkeypatched and artifact bytes are NOT real audio.
  - test_golden_path_real_audio_decodable: the honest P0.8 gate. No audio
    stubs — FakeSpeechProvider emits real MP3 sine tones (P1.0), assembly/QC/
    export run for real, and the exported artifacts must decode via ffprobe
    with plausible durations and correct chapter count/order. Requires ffmpeg
    and ffprobe on PATH (CI installs them; production images ship them).

No network, no AWS credentials required in either tier.
"""
import hashlib
import io
import json
import shutil
import subprocess

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


def _ffprobe(path):
    """Return ffprobe's parsed JSON (format + chapters) for a media file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_chapters", str(path)],
        capture_output=True, check=True, timeout=60,
    )
    return json.loads(out.stdout)


def test_golden_path_real_audio_decodable(engine, api, tmp_path):
    """The honest P0.8 gate: no audio stubs, decodability asserted live.

    upload → job → real synthesis (fake provider, real MP3) → real merge/QC →
    real MP3+M4B export → signed URL → download through the API → ffprobe.
    """
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), (
        "ffmpeg/ffprobe are required for the golden path (CI installs them)"
    )
    from pydub import AudioSegment
    from utils.audio_utils import CHARS_PER_SECOND
    from storage import get_storage
    from db.models import Job

    api.signup("real-audio@example.com")
    r = api.post("/api/synthesize", json={
        "text": BOOK_TEXT,
        "provider": "fake",
        "voice_id": "fake-a",
        "engine": "neural",
        "formats": ["mp3", "m4b"],
        "title": "Real Audio E2E",
        "author": "Test Author",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    from worker import process_one
    assert process_one(worker_id="e2e-real-worker"), "worker found no job"

    r = api.get(f"/api/task/{job_id}")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["status"] == "succeeded", (
        f"unexpected status: {body.get('status')} error={body.get('error')}"
    )
    assert body["progress"] == 100
    assert body["chapters_count"] == 2

    storage = get_storage()
    with session_scope() as s:
        job = s.get(Job, job_id)
        rows = sorted(job.chapters, key=lambda c: c.index)
        assert [c.index for c in rows] == [0, 1], "chapter order must match input"
        titles = [c.title for c in rows]
        assert all(titles), f"chapter titles must be non-empty: {titles}"
        # Every chapter has a durable, checksummed, decodable, non-silent artifact.
        for c in rows:
            assert c.audio_key, f"chapter {c.index} missing audio_key"
            audio = storage.get_bytes(c.audio_key)
            assert hashlib.sha256(audio).hexdigest() == c.audio_sha256
            seg = AudioSegment.from_file(io.BytesIO(audio), format="mp3")
            assert len(seg) > 500, f"chapter {c.index} audio too short to be real"
            assert seg.dBFS > -45, f"chapter {c.index} audio is silent"
        mp3_key, m4b_key = job.output_mp3_key, job.output_m4b_key
    assert mp3_key and m4b_key, "both export formats must be produced"

    # Download the MP3 through the signed URL the API hands out — full loop.
    r = api.get(f"/api/download/{job_id}?format=mp3")
    assert r.status_code == 200, r.get_json()
    url = r.get_json()["url"]
    assert url
    path_and_query = url.split("://", 1)[-1].split("/", 1)[1]
    dl = api.get("/" + path_and_query)
    assert dl.status_code == 200, f"signed URL fetch failed: {dl.status_code}"
    mp3_file = tmp_path / "book.mp3"
    mp3_file.write_bytes(dl.data)

    # The exported artifact decodes via ffprobe with a plausible duration.
    probe = _ffprobe(mp3_file)
    assert "mp3" in probe["format"]["format_name"]
    duration = float(probe["format"]["duration"])
    expected = len(BOOK_TEXT) / CHARS_PER_SECOND
    assert 0.5 * expected < duration < 2.0 * expected + 10, (
        f"duration {duration:.1f}s implausible for {len(BOOK_TEXT)} chars "
        f"(expected ≈{expected:.1f}s)"
    )

    # M4B: decodes, and carries exactly the chapters, in order.
    m4b_file = tmp_path / "book.m4b"
    m4b_file.write_bytes(storage.get_bytes(m4b_key))
    probe = _ffprobe(m4b_file)
    assert any(f in probe["format"]["format_name"] for f in ("mp4", "m4a", "mov"))
    chapters = probe.get("chapters", [])
    assert len(chapters) == 2, f"m4b must carry 2 chapters, got {len(chapters)}"
    starts = [float(c["start_time"]) for c in chapters]
    assert starts == sorted(starts), "m4b chapters out of order"


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
