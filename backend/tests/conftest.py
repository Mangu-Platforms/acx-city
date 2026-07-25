"""Shared test fixtures.

Tests run against DATABASE_URL if it points at Postgres (CI / docker), otherwise
a throwaway SQLite file under a temp dir. Concurrency tests that require real
row-locking are skipped automatically unless a Postgres URL is present.
"""
import os
import tempfile
import uuid

import pytest


@pytest.fixture(scope="session", autouse=True)
def _env_defaults():
    os.environ.setdefault("JWT_SECRET", "test-secret")
    os.environ.setdefault("FLASK_ENV", "testing")
    # Keep synthesis output/cache off the (read-restricted) mounted fs in sandbox.
    tmp = tempfile.mkdtemp(prefix="ab_test_")
    os.environ.setdefault("OUTPUT_FOLDER", os.path.join(tmp, "outputs"))
    os.environ.setdefault("CACHE_FOLDER", os.path.join(tmp, "cache"))
    os.environ.setdefault("UPLOAD_FOLDER", os.path.join(tmp, "uploads"))
    # Storage: local backend rooted in the temp dir; signing secret pinned.
    os.environ.setdefault("STORAGE_BACKEND", "local")
    os.environ.setdefault("STORAGE_LOCAL_ROOT", os.path.join(tmp, "storage"))
    os.environ.setdefault("STORAGE_SIGNING_SECRET", "test-signing-secret")
    yield


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
    """Replace TTS provider + audio assembly so the pipeline runs offline.

    Writes tiny fake mp3 files so QC/assembly code paths that only check for a
    non-empty file succeed, without ffmpeg or network.
    """
    from services.providers.edge_provider import EdgeProvider
    from utils.audio_utils import AudioUtils

    monkeypatch.setattr(EdgeProvider, "is_available", lambda self: True)
    monkeypatch.setattr(EdgeProvider, "synthesize", lambda self, text, voice_id, engine="neural": b"ID3fakeaudio" + text[:8].encode())

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

    # Normalization "fails" gracefully: the pipeline logs a warning and keeps
    # the raw chapter audio, which is exactly what we want offline.
    def fake_normalize(inp, out, target_dBFS=None):
        return False

    monkeypatch.setattr(AudioUtils, "merge_audio_files", staticmethod(fake_merge))
    monkeypatch.setattr(AudioUtils, "qc_check", staticmethod(fake_qc))
    monkeypatch.setattr(AudioUtils, "export_m4b", staticmethod(fake_m4b))
    monkeypatch.setattr(AudioUtils, "concat_audio_files", staticmethod(fake_concat))
    monkeypatch.setattr(AudioUtils, "normalize_audio", staticmethod(fake_normalize))
    # Patch the already-instantiated pipeline singletons too.
    import jobs.pipeline as pl
    monkeypatch.setattr(pl._audio, "merge_audio_files", fake_merge)
    monkeypatch.setattr(pl._audio, "qc_check", fake_qc)
    monkeypatch.setattr(pl._audio, "export_m4b", fake_m4b)
    monkeypatch.setattr(pl._audio, "concat_audio_files", fake_concat)
    monkeypatch.setattr(pl._audio, "normalize_audio", fake_normalize)
    monkeypatch.setattr(pl._registry.get("edge"), "is_available", lambda: True)
    monkeypatch.setattr(pl._registry.get("edge"), "synthesize",
                        lambda text, voice_id, engine="neural": b"ID3fake" + text[:8].encode())
    yield
