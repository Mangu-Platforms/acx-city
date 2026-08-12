"""P1.6 gate: every export decodes via ffprobe; chapter count and order
verified; the manifest is reproducible.

All exports build from the same active-revision set. The manifest carries
input checksums (chapter audio sha, source-text sha, synthesis_id) and
output checksums, with deterministic serialization — an unchanged re-export
reproduces it byte-for-byte. EPUB content comes from revision source_text:
the exact spoken text, lexicon replacements included.
"""
import io
import json
import shutil
import subprocess
import zipfile

import pytest
from sqlalchemy import select

from db.session import session_scope
from db import models as m
from db.voxengine_models import PronunciationLexicon
from worker import process_one

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe required",
)

BODY = "The lighthouse keeper counted the ships as they passed the headland. " * 9


def _book_text():
    parts = []
    for n, extra in ((1, "The first tide came early. "),
                     (2, "Doctor Nguyen signalled from the tower. "),
                     (3, "The third watch ended at dawn. ")):
        parts.append(f"Chapter {n}: Watch {n}\n\n{BODY}{extra}")
    return "\n\n".join(parts)


@pytest.fixture()
def api(client):
    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None

        def signup(self, email="p16@example.com", password="securepass123"):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            self._token = r.get_json()["token"]

        @property
        def _headers(self):
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path, **kw):
            return self._c.get(path, headers=self._headers, **kw)

        def post(self, path, **kw):
            return self._c.post(path, headers=self._headers, **kw)

    return _API(client)


def _ffprobe(tmp_path, data, name):
    p = tmp_path / name
    p.write_bytes(data)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_chapters", str(p)],
        capture_output=True, check=True, timeout=60,
    )
    return json.loads(out.stdout)


def test_exports_decode_manifest_reproducible_epub_from_revisions(engine, api, tmp_path):
    from storage import get_storage
    import hashlib

    api.signup()
    r = api.post("/api/synthesize", json={
        "text": _book_text(), "provider": "fake", "voice_id": "fake-a",
        "engine": "neural", "formats": ["mp3", "m4b"],
        "title": "Manifest Book", "author": "Keeper",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]

    # Lexicon BEFORE synthesis: the spoken text (and hence the revisions and
    # the EPUB) carries the phonetic replacement.
    with session_scope() as s:
        project_id = s.get(m.Job, job_id).project_id
        s.add(PronunciationLexicon(project_id=project_id, word="Nguyen",
                                   phonetic_spelling="NWIN"))

    assert process_one("p16-run") is True
    with session_scope() as s:
        job = s.get(m.Job, job_id)
        assert job.status == m.JobStatus.succeeded, job.error
        rows = sorted(job.chapters, key=lambda c: c.index)
        row_shas = {c.index: c.audio_sha256 for c in rows}
        rev_text_shas = {
            c.index: hashlib.sha256(
                c.revisions[-1].source_text.encode("utf-8")).hexdigest()
            for c in rows
        }
        mp3_key, m4b_key = job.output_mp3_key, job.output_m4b_key

    storage = get_storage()

    # --- Manifest: ordered, checksums match reality -------------------------
    r = api.get(f"/api/jobs/{job_id}/manifest")
    assert r.status_code == 200, r.get_json()
    manifest_bytes_1 = r.data
    manifest = json.loads(manifest_bytes_1)
    assert [c["index"] for c in manifest["chapters"]] == [0, 1, 2]
    for entry in manifest["chapters"]:
        assert entry["audio_sha256"] == row_shas[entry["index"]]
        assert entry["source_text_sha256"] == rev_text_shas[entry["index"]]
        assert entry["synthesis_id"]
        assert entry["revision_number"] == 1
    mp3_bytes = storage.get_bytes(mp3_key)
    m4b_bytes = storage.get_bytes(m4b_key)
    assert manifest["outputs"]["mp3"] == hashlib.sha256(mp3_bytes).hexdigest()
    assert manifest["outputs"]["m4b"] == hashlib.sha256(m4b_bytes).hexdigest()

    # --- Every export decodes; chapter count and order verified -------------
    probe = _ffprobe(tmp_path, mp3_bytes, "book.mp3")
    assert "mp3" in probe["format"]["format_name"]
    assert float(probe["format"]["duration"]) > 30

    probe = _ffprobe(tmp_path, m4b_bytes, "book.m4b")
    assert any(f in probe["format"]["format_name"] for f in ("mp4", "m4a", "mov"))
    chapters = probe.get("chapters", [])
    assert len(chapters) == 3, f"m4b must carry 3 chapters, got {len(chapters)}"
    starts = [float(c["start_time"]) for c in chapters]
    assert starts == sorted(starts)

    # --- EPUB builds from the active revisions (spoken text) ----------------
    r = api.get(f"/api/jobs/{job_id}/export/epub")
    assert r.status_code == 200, r.get_json()
    url = r.get_json()["url"]
    epub_resp = api.get("/" + url.split("://", 1)[-1].split("/", 1)[1])
    assert epub_resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(epub_resp.data))
    xhtml = "".join(
        zf.read(n).decode("utf-8", errors="replace")
        for n in zf.namelist() if n.endswith((".xhtml", ".html"))
    )
    assert "NWIN" in xhtml, "EPUB must carry the spoken (lexicon-applied) text"
    assert "Nguyen" not in xhtml
    assert "Watch 1" in xhtml and "Watch 3" in xhtml

    # --- Reproducible: unchanged re-export → byte-identical manifest --------
    r = api.post(f"/api/jobs/{job_id}/rerender")
    assert r.status_code == 202, r.get_json()
    assert process_one("p16-rerun") is True
    with session_scope() as s:
        assert s.get(m.Job, job_id).status == m.JobStatus.succeeded
    r = api.get(f"/api/jobs/{job_id}/manifest")
    assert r.status_code == 200
    assert r.data == manifest_bytes_1, (
        "an unchanged re-export must reproduce the manifest byte-for-byte"
    )
