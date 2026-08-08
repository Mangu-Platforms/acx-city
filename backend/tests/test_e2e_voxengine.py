"""End-to-end tests for the VoxEngine blueprint (backend/api/voxengine.py).

Exercises the HTTP surface with a real per-test DB:
  characters (create/list/upsert/validation, cross-org isolation),
  lexicon (create/list/delete lifecycle),
  pipeline status + trace (fresh-project and zero-trace shapes),
  chapter rerender (Celery-gated 503) and waveform stub.

Offline and deterministic: no worker runs, no synthesis, no network.
"""
import importlib
import uuid

import pytest

from db.session import session_scope


PASSWORD = "pass1234567"


@pytest.fixture()
def api(client):
    """Thin wrapper around the Flask test client with JSON helpers."""

    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None
            self.user_id = None
            self.org_id = None

        def signup(self, email="vox@example.com", password=PASSWORD):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            self._token = body["token"]
            self.user_id = body["user"]["id"]
            self.org_id = body["organization"]["id"]
            return body

        @property
        def _headers(self):
            assert self._token, "call signup() first"
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path, **kw):
            return self._c.get(path, headers=self._headers, **kw)

        def post(self, path, **kw):
            return self._c.post(path, headers=self._headers, **kw)

        def delete(self, path, **kw):
            return self._c.delete(path, headers=self._headers, **kw)

    return _API(client)


def _make_project(org_id, user_id, title="VoxEngine Book"):
    """Seed a Project row directly and return its id."""
    from db.models import Project

    with session_scope() as s:
        p = Project(
            organization_id=org_id,
            created_by=user_id,
            title=title,
            source_text="Chapter 1: Test\n\nHello world.",
        )
        s.add(p)
        s.flush()
        return p.id


def _make_job_with_chapter(org_id, project_id, user_id, duration_s=12.5):
    """Seed a Job + one ChapterResult directly; return (job_id, chapter_id)."""
    from db.models import ChapterResult, Job

    with session_scope() as s:
        job = Job(
            organization_id=org_id,
            project_id=project_id,
            created_by=user_id,
            provider="fake",
            voice_id="fake-a",
            engine="neural",
            formats="mp3",
        )
        s.add(job)
        s.flush()
        chapter = ChapterResult(
            job_id=job.id,
            index=0,
            title="Chapter 1: Test",
            duration_s=duration_s,
        )
        s.add(chapter)
        s.flush()
        return job.id, chapter.id


def _second_org_client(email="otherorg@example.com"):
    """Fresh Flask client + auth headers for a second, unrelated org."""
    import app as appmod

    importlib.reload(appmod)
    appmod.app.config.update(TESTING=True)
    other = appmod.app.test_client()
    r = other.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.get_json()
    token = r.get_json()["token"]
    return other, {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 1. Characters: create, list, upsert, validation
# --------------------------------------------------------------------------- #

def test_characters_create_list_upsert_and_validation(engine, api):
    api.signup()
    project_id = _make_project(api.org_id, api.user_id)

    # Create
    r = api.post(f"/api/projects/{project_id}/characters", json={
        "character_name": "Alice",
        "voice_slug": "en-US-x",
        "is_narrator": False,
    })
    assert r.status_code == 201, r.get_json()
    created = r.get_json()
    assert set(created.keys()) == {"id", "created"}
    assert created["created"] is True
    char_id = created["id"]
    assert char_id

    # List: exactly one entry with the full field shape
    r = api.get(f"/api/projects/{project_id}/characters")
    assert r.status_code == 200
    chars = r.get_json()
    assert isinstance(chars, list) and len(chars) == 1
    assert chars[0] == {
        "id": char_id,
        "character_name": "Alice",
        "voice_id": None,
        "voice_slug": "en-US-x",
        "pitch_adjustment": 1.0,
        "speed_adjustment": 1.0,
        "base_emotion": "neutral",
        "is_narrator": False,
        "attribution_confidence": None,
        "notes": None,
    }

    # Upsert: same character_name with a different voice_slug updates in place
    r = api.post(f"/api/projects/{project_id}/characters", json={
        "character_name": "Alice",
        "voice_slug": "en-GB-y",
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"id": char_id, "updated": True}

    r = api.get(f"/api/projects/{project_id}/characters")
    assert r.status_code == 200
    chars = r.get_json()
    assert len(chars) == 1
    assert chars[0]["id"] == char_id
    assert chars[0]["voice_slug"] == "en-GB-y"
    assert chars[0]["character_name"] == "Alice"

    # Validation: missing character_name -> 400
    r = api.post(f"/api/projects/{project_id}/characters", json={"voice_slug": "en-US-z"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "character_name required"}


# --------------------------------------------------------------------------- #
# 2. Cross-org isolation
# --------------------------------------------------------------------------- #

def test_characters_cross_org_is_404(engine, api):
    api.signup("owner-vox@example.com")
    project_id = _make_project(api.org_id, api.user_id)

    r = api.post(f"/api/projects/{project_id}/characters", json={
        "character_name": "Alice",
        "voice_slug": "en-US-x",
    })
    assert r.status_code == 201, r.get_json()

    # Owner can list.
    r = api.get(f"/api/projects/{project_id}/characters")
    assert r.status_code == 200
    assert len(r.get_json()) == 1

    # A different org gets a 404 (not 403 — no existence leak).
    other, other_headers = _second_org_client()
    r2 = other.get(f"/api/projects/{project_id}/characters", headers=other_headers)
    assert r2.status_code == 404, (
        f"cross-org characters access should 404, got {r2.status_code}: {r2.get_json()}"
    )


# --------------------------------------------------------------------------- #
# 3. Lexicon lifecycle
# --------------------------------------------------------------------------- #

def test_lexicon_create_list_delete_lifecycle(engine, api):
    api.signup()
    project_id = _make_project(api.org_id, api.user_id)

    # Empty to start
    r = api.get(f"/api/projects/{project_id}/lexicon")
    assert r.status_code == 200
    assert r.get_json() == []

    # Create an entry ("word" is the only required field)
    r = api.post(f"/api/projects/{project_id}/lexicon", json={
        "word": "Hermione",
        "ipa_phoneme": "/hɜːrˈmaɪ.əni/",
        "phonetic_spelling": "her-MY-uh-nee",
        "context_note": "protagonist name",
    })
    assert r.status_code == 201, r.get_json()
    created = r.get_json()
    assert set(created.keys()) == {"id", "created"}
    assert created["created"] is True
    entry_id = created["id"]

    # Missing word -> 400
    r = api.post(f"/api/projects/{project_id}/lexicon", json={"ipa_phoneme": "/x/"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "word required"}

    # List shows the entry with the full field shape
    r = api.get(f"/api/projects/{project_id}/lexicon")
    assert r.status_code == 200
    entries = r.get_json()
    assert len(entries) == 1
    assert entries[0] == {
        "id": entry_id,
        "word": "Hermione",
        "ipa_phoneme": "/hɜːrˈmaɪ.əni/",
        "phonetic_spelling": "her-MY-uh-nee",
        "context_note": "protagonist name",
        "source": "manual",
        "is_global": False,
    }

    # Delete it
    r = api.delete(f"/api/projects/{project_id}/lexicon/{entry_id}")
    assert r.status_code == 200
    assert r.get_json() == {"deleted": True}

    # List is empty again
    r = api.get(f"/api/projects/{project_id}/lexicon")
    assert r.status_code == 200
    assert r.get_json() == []

    # Deleting a random uuid -> 404
    r = api.delete(f"/api/projects/{project_id}/lexicon/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Entry not found"}


# --------------------------------------------------------------------------- #
# 4. Pipeline status + trace
# --------------------------------------------------------------------------- #

def test_pipeline_status_and_trace_shapes(engine, api):
    api.signup()
    project_id = _make_project(api.org_id, api.user_id)

    # Fresh project (no job yet): both endpoints report no job.
    r = api.get(f"/api/projects/{project_id}/pipeline/status")
    assert r.status_code == 404
    assert r.get_json() == {"error": "No job found for this project"}

    r = api.get(f"/api/projects/{project_id}/pipeline/trace/1")
    assert r.status_code == 404
    assert r.get_json() == {"error": "No job found"}

    # With a job but no pipeline traces: zero-state status shape.
    job_id, _chapter_id = _make_job_with_chapter(api.org_id, project_id, api.user_id)
    r = api.get(f"/api/projects/{project_id}/pipeline/status")
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {
        "job_id": job_id,
        "status": "queued",
        "chapters_total": 0,
        "chapters_completed": 0,
        "chapters_failed": 0,
        "total_cost_usd": 0.0,
        "traces": [],
    }

    # Trace for a chapter that has no trace row -> 404 with chapter number.
    r = api.get(f"/api/projects/{project_id}/pipeline/trace/1")
    assert r.status_code == 404
    assert r.get_json() == {"error": "No trace for chapter 1"}


# --------------------------------------------------------------------------- #
# 5. Rerender: Celery-gated 503 and 404 on unknown chapter
# --------------------------------------------------------------------------- #

def test_rerender_is_celery_gated_503_and_404(engine, api):
    api.signup()
    project_id = _make_project(api.org_id, api.user_id)
    _job_id, chapter_id = _make_job_with_chapter(api.org_id, project_id, api.user_id)

    r = api.post(f"/api/chapters/{chapter_id}/rerender")
    assert r.status_code == 503, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"error"}
    assert "Celery" in body["error"]

    # Nonexistent chapter -> 404
    r = api.post(f"/api/chapters/{uuid.uuid4()}/rerender")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Chapter not found"}


# --------------------------------------------------------------------------- #
# 6. Waveform stub shape + cross-org isolation
# --------------------------------------------------------------------------- #

def test_waveform_shape_and_cross_org_404(engine, api):
    api.signup("wave-owner@example.com")
    project_id = _make_project(api.org_id, api.user_id)
    _job_id, chapter_id = _make_job_with_chapter(
        api.org_id, project_id, api.user_id, duration_s=12.5
    )

    r = api.get(f"/api/chapters/{chapter_id}/waveform")
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {
        "chapter_id": chapter_id,
        "duration_s": 12.5,
        "sample_rate": 24000,
        "peaks": [],
        "markers": [],
    }

    # Another org's chapter is invisible.
    other, other_headers = _second_org_client("wave-other@example.com")
    r2 = other.get(f"/api/chapters/{chapter_id}/waveform", headers=other_headers)
    assert r2.status_code == 404, (
        f"cross-org waveform access should 404, got {r2.status_code}: {r2.get_json()}"
    )
    assert r2.get_json() == {"error": "Chapter not found"}
