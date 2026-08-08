"""End-to-end tests for the voice catalog API (services/voice_catalog_endpoints.py).

Covers:
  - GET /api/voices          list envelope, org/global visibility, field-level shape
  - filters                  gender / provider / search
  - pagination               per_page + pages/total math
  - GET /api/voices/<id>     detail shape + org-scoping 404s
  - GET /api/voices/<id>/sample   302 redirect vs on-demand synthesis (FakeSpeechProvider)
  - clone lifecycle          create -> list -> delete -> list empty, plus validation 400s
  - unauthenticated access   401

Deterministic and offline: voice A uses provider "fake" (FakeSpeechProvider is
always available and returns b"ID3fake" + sha256(voice_id:text)[:16]).
"""
import io
import uuid

import pytest

from db.session import session_scope


@pytest.fixture()
def api(client):
    """Thin wrapper around the Flask test client with auth helpers."""

    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="catalog@example.com", password="securepass123"):
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

        def delete(self, path, **kw):
            return self._c.delete(path, headers=self._headers, **kw)

    return _API(client)


def _seed_catalog():
    """Seed the StockVoice catalog directly in the DB.

    Rows:
      a: global, active, provider="fake"/"fake-a", no sample URL, no latent
      b: global, active, provider="edge", sample URL + latent set, male
      c: global, INACTIVE (must never be visible)
      d: org-scoped to a different org (must never be visible to our caller)

    Returns a dict of ids: {"a", "b", "c", "d", "other_org"}.
    """
    from db.models import Organization
    from db.voxengine_models import StockVoice

    ids = {}
    with session_scope() as s:
        other_org = Organization(name="Other Org")
        s.add(other_org)
        s.flush()
        ids["other_org"] = other_org.id

        a = StockVoice(
            slug="aria-fake",
            display_name="Aria Fakevoice",
            gender="female",
            accent="american",
            provider="fake",
            provider_voice_id="fake-a",
            sample_audio_url=None,
            style_tags=[],
            languages=["en"],
            emotion_tags=[],
            is_active=True,
        )
        b = StockVoice(
            slug="bruno-edge",
            display_name="Bruno Edgevoice",
            gender="male",
            accent="british",
            provider="edge",
            provider_voice_id="en-GB-RyanNeural",
            sample_audio_url="https://example.com/b.mp3",
            latent_s3_key="latents/bruno.npy",
            style_tags=[],
            languages=["en"],
            emotion_tags=[],
            is_active=True,
        )
        c = StockVoice(
            slug="carla-inactive",
            display_name="Carla Inactive",
            gender="female",
            accent="american",
            provider="edge",
            provider_voice_id="en-US-CarlaNeural",
            style_tags=[],
            languages=["en"],
            emotion_tags=[],
            is_active=False,
        )
        d = StockVoice(
            slug="dora-otherorg",
            display_name="Dora Otherorg",
            gender="female",
            accent="american",
            provider="edge",
            provider_voice_id="en-US-DoraNeural",
            style_tags=[],
            languages=["en"],
            emotion_tags=[],
            is_active=True,
            organization_id=other_org.id,
        )
        s.add_all([a, b, c, d])
        s.flush()
        ids["a"], ids["b"], ids["c"], ids["d"] = a.id, b.id, c.id, d.id
    return ids


# --------------------------------------------------------------------------- #
# 1. Listing: envelope + visibility + field-level shape
# --------------------------------------------------------------------------- #

def test_list_voices_envelope_visibility_and_fields(engine, api):
    api.signup()
    ids = _seed_catalog()

    r = api.get("/api/voices")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()

    # Exact envelope shape
    assert set(body.keys()) == {"voices", "total", "page", "pages"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 1

    # Only the two active global voices are visible, ordered by display_name asc.
    slugs = [v["slug"] for v in body["voices"]]
    assert slugs == ["aria-fake", "bruno-edge"]
    assert ids["c"] not in [v["id"] for v in body["voices"]]
    assert ids["d"] not in [v["id"] for v in body["voices"]]

    # Field-level assert on voice A (full serialized shape).
    a = body["voices"][0]
    assert isinstance(a["created_at"], str) and a["created_at"]
    assert a == {
        "id": ids["a"],
        "slug": "aria-fake",
        "display_name": "Aria Fakevoice",
        "gender": "female",
        "accent": "american",
        "age_range": None,
        "style_tags": [],
        "description": None,
        "provider": "fake",
        "provider_voice_id": "fake-a",
        "sample_audio_url": None,
        "languages": ["en"],
        "emotion_tags": [],
        "is_active": True,
        "is_cloneable": False,
        "source": "mangu",
        "has_latent_embedding": False,
        "created_at": a["created_at"],
    }

    # Voice B has a sample URL and a latent embedding.
    b = body["voices"][1]
    assert b["sample_audio_url"] == "https://example.com/b.mp3"
    assert b["has_latent_embedding"] is True


# --------------------------------------------------------------------------- #
# 2. Filters
# --------------------------------------------------------------------------- #

def test_list_voices_filters(engine, api):
    api.signup()
    _seed_catalog()

    # gender=male -> only B
    r = api.get("/api/voices?gender=male")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["total"] == 1
    assert [v["slug"] for v in body["voices"]] == ["bruno-edge"]

    # provider=fake -> only A
    r = api.get("/api/voices?provider=fake")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["total"] == 1
    assert [v["slug"] for v in body["voices"]] == ["aria-fake"]

    # search on a substring of A's display_name -> only A
    r = api.get("/api/voices?search=Aria")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["total"] == 1
    assert [v["slug"] for v in body["voices"]] == ["aria-fake"]


# --------------------------------------------------------------------------- #
# 3. Pagination
# --------------------------------------------------------------------------- #

def test_list_voices_pagination(engine, api):
    api.signup()
    _seed_catalog()

    r = api.get("/api/voices?per_page=1")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert len(body["voices"]) == 1
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 2
    assert body["voices"][0]["slug"] == "aria-fake"  # first by display_name asc

    # Page 2 holds the other voice.
    r = api.get("/api/voices?per_page=1&page=2")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert len(body["voices"]) == 1
    assert body["page"] == 2
    assert body["pages"] == 2
    assert body["voices"][0]["slug"] == "bruno-edge"


# --------------------------------------------------------------------------- #
# 4. Detail + org scoping
# --------------------------------------------------------------------------- #

def test_voice_detail_and_org_scoping(engine, api):
    api.signup()
    ids = _seed_catalog()

    r = api.get(f"/api/voices/{ids['a']}")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    # Detail = catalog fields + detail-only keys
    assert set(body.keys()) == {
        "id", "slug", "display_name", "gender", "accent", "age_range",
        "style_tags", "description", "provider", "provider_voice_id",
        "sample_audio_url", "languages", "emotion_tags", "is_active",
        "is_cloneable", "source", "has_latent_embedding", "created_at",
        "organization_id", "voice_city_voice_id",
    }
    assert body["id"] == ids["a"]
    assert body["organization_id"] is None  # global voice
    assert body["voice_city_voice_id"] is None

    # A voice scoped to a different org is invisible -> 404
    r = api.get(f"/api/voices/{ids['d']}")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Voice not found"}

    # Random uuid -> 404
    r = api.get(f"/api/voices/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.get_json() == {"error": "Voice not found"}


# --------------------------------------------------------------------------- #
# 5. Samples: 302 redirect vs on-demand synthesis
# --------------------------------------------------------------------------- #

def test_voice_sample_redirects_to_prerecorded_url(engine, api):
    api.signup()
    ids = _seed_catalog()

    r = api.get(f"/api/voices/{ids['b']}/sample")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://example.com/b.mp3"


def test_voice_sample_synthesized_on_demand(engine, api):
    api.signup()
    ids = _seed_catalog()

    r = api.get(f"/api/voices/{ids['a']}/sample")
    assert r.status_code == 200
    assert r.mimetype == "audio/mpeg"
    assert r.data.startswith(b"ID3fake")
    # FakeSpeechProvider output is b"ID3fake" + 16 digest bytes — nothing else.
    assert len(r.data) == len(b"ID3fake") + 16
    assert r.headers["Cache-Control"] == "public, max-age=86400"


# --------------------------------------------------------------------------- #
# 6. Clone lifecycle
# --------------------------------------------------------------------------- #

def test_clone_lifecycle(engine, api):
    api.signup()

    # Create
    r = api.post(
        "/api/voices/clone",
        data={"audio": (io.BytesIO(b"RIFF....fakewav"), "ref.wav"), "name": "My Clone"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"clone_id", "name", "status", "message"}
    assert body["name"] == "My Clone"
    assert body["status"] == "processing"
    assert isinstance(body["clone_id"], str) and body["clone_id"]
    assert isinstance(body["message"], str) and body["message"]
    clone_id = body["clone_id"]

    # List: exactly one, full field-level shape
    r = api.get("/api/voices/clones")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert set(body.keys()) == {"clones", "total"}
    assert body["total"] == 1
    assert len(body["clones"]) == 1
    c = body["clones"][0]
    assert isinstance(c["created_at"], str) and c["created_at"]
    assert c == {
        "id": clone_id,
        "name": "My Clone",
        "status": "processing",
        "provider": "fish_speech",
        "reference_duration_seconds": None,
        "safety_similarity_score": None,
        "error": None,
        "created_at": c["created_at"],
    }

    # Delete
    r = api.delete(f"/api/voices/clones/{clone_id}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"clone_id": clone_id, "deleted": True}

    # List again: empty
    r = api.get("/api/voices/clones")
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"clones": [], "total": 0}


def test_clone_validation_errors(engine, api):
    api.signup()

    # Disallowed extension -> 400
    r = api.post(
        "/api/voices/clone",
        data={"audio": (io.BytesIO(b"MZfake"), "malware.exe"), "name": "Bad Clone"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "error" in r.get_json()

    # Missing name -> 400
    r = api.post(
        "/api/voices/clone",
        data={"audio": (io.BytesIO(b"RIFF....fakewav"), "ref.wav")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "error" in r.get_json()


# --------------------------------------------------------------------------- #
# 7. Auth
# --------------------------------------------------------------------------- #

def test_list_voices_requires_auth(engine, client):
    r = client.get("/api/voices")
    assert r.status_code == 401
    body = r.get_json()
    assert "error" in body
