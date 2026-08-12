"""Shared test fixtures.

Tests run against DATABASE_URL if it points at Postgres (CI / docker), otherwise
a throwaway SQLite file under a temp dir. Concurrency tests that require real
row-locking are skipped automatically unless a Postgres URL is present.
"""
import os
import tempfile
import uuid

import pytest

# Env defaults must be set at conftest IMPORT time, not in a fixture: several
# application modules bind env-derived paths when first imported (e.g.
# jobs.pipeline instantiates SynthesisCache(CACHE_FOLDER) at module level),
# and pytest imports test modules during COLLECTION — before any fixture
# runs. test_jobs.py imports `worker` at module top level, so with
# fixture-time env the whole suite silently ran against the developer's real
# backend/cache directory, where stale pre-P1.0 fake entries poisoned real
# synthesis runs (see docs/remediation/FOUND.md, 2026-08-12).
_TEST_TMP = tempfile.mkdtemp(prefix="ab_test_")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("OUTPUT_FOLDER", os.path.join(_TEST_TMP, "outputs"))
os.environ.setdefault("CACHE_FOLDER", os.path.join(_TEST_TMP, "cache"))
os.environ.setdefault("UPLOAD_FOLDER", os.path.join(_TEST_TMP, "uploads"))
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_LOCAL_ROOT", os.path.join(_TEST_TMP, "storage"))
os.environ.setdefault("STORAGE_SIGNING_SECRET", "test-signing-secret")


@pytest.fixture()
def db_url():
    """A fresh database URL per test.

    Postgres: uses DATABASE_URL as-is (assumed clean test DB; schema created and
    dropped per test). SQLite: a unique temp file.
    """
    configured = os.getenv("DATABASE_URL", "")
    if configured.startswith("postgres"):
        return configured
    path = os.path.join(tempfile.gettempdir(), f"abtest_{uuid.uuid4().hex}.db")
    return f"sqlite:///{path}"


@pytest.fixture()
def engine(db_url):
    from db.session import init_engine
    from db.base import Base
    import db.models  # noqa: F401 register models

    # Pin DATABASE_URL so any code path that calls init_engine() (e.g. importing
    # app.py) binds to this same per-test database.
    os.environ["DATABASE_URL"] = db_url
    eng = init_engine(db_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def is_postgres(engine):
    return engine.dialect.name == "postgresql"


@pytest.fixture()
def client(engine):
    """Flask test client bound to the per-test engine."""
    import importlib
    import app as appmod
    importlib.reload(appmod)  # rebind module-level engine/session usage
    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()


@pytest.fixture()
def auth_headers(client):
    """Signs up a user and returns (headers, token, org_id) for that user."""
    def _make(email="user@example.com", password="password123"):
        r = client.post("/api/auth/signup", json={"email": email, "password": password})
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        return {"Authorization": f"Bearer {body['token']}"}, body["organization"]["id"]
    return _make


@pytest.fixture()
def stub_pipeline(monkeypatch):
    """Stub audio assembly so the pipeline runs offline without ffmpeg.

    Synthesis is handled by FakeSpeechProvider (registered as "fake" in the
    registry) — no monkeypatching of Edge needed when tests use provider="fake".
    The audio util stubs make assembly/QC/export succeed without real ffmpeg.
    """
    from utils.audio_utils import AudioUtils

    def fake_merge(paths, out, gap_duration=1000):
        with open(out, "wb") as f:
            f.write(b"ID3merged")
        return True

    def fake_qc(path):
        return {"duration_s": 12.0, "loudness_dbfs": -20.0, "peak_dbfs": -3.0,
                "silence_ratio": 0.05, "clipping": False, "issues": [], "passed": True}

    def fake_m4b(files, titles, out, book_title="Audiobook", author=""):
        with open(out, "wb") as f:
            f.write(b"M4Bfake")
        return True

    def fake_concat(paths, out, gap_ms=1500):
        with open(out, "wb") as f:
            f.write(b"ID3concat")
        return True

    def fake_normalize(inp, out, target_dBFS=None):
        return False

    # Patch at CLASS level only. The pipeline's singletons (pl._audio, the
    # registry's providers) resolve these through the class, so class patches
    # reach them. Do NOT monkeypatch the singleton instances after patching
    # the class: monkeypatch would capture the already-patched class value as
    # the "original" and permanently freeze the stub onto the singleton at
    # teardown — any real-audio test running after a stubbed one then silently
    # runs stubbed (found 2026-08-12; see docs/remediation/FOUND.md).
    monkeypatch.setattr(AudioUtils, "merge_audio_files", staticmethod(fake_merge))
    monkeypatch.setattr(AudioUtils, "qc_check", staticmethod(fake_qc))
    monkeypatch.setattr(AudioUtils, "export_m4b", staticmethod(fake_m4b))
    monkeypatch.setattr(AudioUtils, "concat_audio_files", staticmethod(fake_concat))
    monkeypatch.setattr(AudioUtils, "normalize_audio", staticmethod(fake_normalize))
    from services.providers.edge_provider import EdgeProvider
    monkeypatch.setattr(EdgeProvider, "is_available", lambda self: True)
    monkeypatch.setattr(EdgeProvider, "synthesize",
                        lambda self, text, voice_id, engine="neural": b"ID3fakeaudio" + text[:8].encode())
    # Media validation (P1.1) is a module-level function in jobs.pipeline;
    # stubbed tests produce fake bytes, so validation must be stubbed with
    # the rest of the audio layer. This is a function patch on the module
    # namespace — no singleton involved, so no freeze hazard.
    from services.media_validation import MediaValidationResult
    import jobs.pipeline as _pl_for_validation
    monkeypatch.setattr(
        _pl_for_validation, "validate_media",
        lambda path, expected_chars=None, expected_extra_s=0.0: MediaValidationResult(
            ok=True, reason=None, detail="stubbed",
            header_duration_s=12.0, decoded_duration_s=12.0, dbfs=-20.0,
        ),
    )
    # Defensively drop any instance attributes that would shadow the class
    # patches (left over from the pre-fix behavior within a process).
    import jobs.pipeline as pl
    _stub_names = ("merge_audio_files", "qc_check", "export_m4b",
                   "concat_audio_files", "normalize_audio")
    for _n in _stub_names:
        if _n in vars(pl._audio):
            delattr(pl._audio, _n)
    _edge = pl._registry.get("edge")
    for _n in ("is_available", "synthesize"):
        if _n in vars(_edge):
            delattr(_edge, _n)
    yield
