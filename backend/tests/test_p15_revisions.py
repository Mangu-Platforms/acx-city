"""P1.5 gate: chapter revisions + selective rerender.

Change one word's pronunciation in a 20-chapter book: only the chapters
containing that word re-synthesize, the UsageEvent count for the other 18 is
unchanged, and prior audio stays playable throughout. Every synthesis writes
an immutable ChapterRevision carrying the exact spoken source_text (which is
what unblocks EPUB export in P1.6).

Real audio end to end: fake-paid provider, real assembly, no stubs.
"""
import shutil

import pytest
from sqlalchemy import func, select

from db.session import session_scope
from db import models as m
from worker import process_one

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobeXX".replace("XX", ""))),
    reason="ffmpeg/ffprobe required",
)

BODY = "The caravan moved through the high passes at first light and made camp late. " * 8
NGUYEN_CHAPTERS = {3, 17}  # 1-indexed chapter numbers containing the word


def _book_text():
    parts = []
    for n in range(1, 21):
        extra = (" Doctor Nguyen appeared at dusk with news from the coast. "
                 if n in NGUYEN_CHAPTERS else " The night settled quietly over the camp. ")
        # Each chapter's body must be unique: identical chapter texts would
        # share one synthesis-cache entry, and cache hits legitimately do not
        # bill — which would make the per-chapter UsageEvent arithmetic
        # meaningless.
        unique = f" On day {n} the ridge line counted {n * 7} switchbacks. "
        parts.append(f"Chapter {n}: Part {n}\n\n{BODY}{unique}{extra}")
    return "\n\n".join(parts)


@pytest.fixture()
def api(client):
    class _API:
        def __init__(self, c):
            self._c = c
            self._token = None
            self.org_id = None

        def signup(self, email="p15@example.com", password="securepass123"):
            r = self._c.post("/api/auth/signup", json={"email": email, "password": password})
            assert r.status_code == 200, r.get_json()
            body = r.get_json()
            self._token = body["token"]
            self.org_id = body["organization"]["id"]
            return body

        @property
        def _headers(self):
            return {"Authorization": f"Bearer {self._token}"}

        def get(self, path, **kw):
            return self._c.get(path, headers=self._headers, **kw)

        def post(self, path, **kw):
            return self._c.post(path, headers=self._headers, **kw)

    return _API(client)


def _usage(session, org_id):
    return session.execute(
        select(func.count()).select_from(m.UsageEvent)
        .where(m.UsageEvent.organization_id == org_id)
    ).scalar()


def _chapter_state(session, job_id):
    """{index: (sha, active_revision_id, [revision numbers])}"""
    job = session.get(m.Job, job_id)
    state = {}
    for c in sorted(job.chapters, key=lambda c: c.index):
        state[c.index] = (
            c.audio_sha256, c.active_revision_id,
            [(r.revision_number, r.status) for r in c.revisions],
        )
    return state


def test_selective_rerender_after_lexicon_edit(engine, api):
    api.signup()
    r = api.post("/api/synthesize", json={
        "text": _book_text(), "provider": "fake-paid", "voice_id": "fake-a",
        "engine": "neural", "formats": ["mp3"], "title": "Revisions Book",
    })
    assert r.status_code == 200, r.get_json()
    job_id = r.get_json()["task_id"]
    with session_scope() as s:
        project_id = s.get(m.Job, job_id).project_id

    assert process_one("p15-first") is True
    with session_scope() as s:
        job = s.get(m.Job, job_id)
        assert job.status == m.JobStatus.succeeded, job.error
        before = _chapter_state(s, job_id)
        usage_before = _usage(s, api.org_id)
        assert len(before) == 20, f"expected 20 chapters, got {len(before)}"
        assert usage_before == 20, "one billable chunk per chapter expected"
        for idx, (sha, active, revs) in before.items():
            assert sha and active, f"chapter {idx} missing artifact/revision"
            assert [n for n, _ in revs] == [1]

    # Edit one word's pronunciation through the API.
    r = api.post(f"/api/projects/{project_id}/lexicon", json={
        "word": "Nguyen", "phonetic_spelling": "NWIN",
    })
    assert r.status_code in (200, 201), r.get_json()

    # Trigger the rerender through the API.
    r = api.post(f"/api/jobs/{job_id}/rerender")
    assert r.status_code == 202, r.get_json()

    # Prior audio is playable while the rerender is queued: the stream
    # endpoint serves the existing durable artifact for an affected chapter.
    affected0 = sorted(n - 1 for n in NGUYEN_CHAPTERS)  # 0-indexed
    r = api.get(f"/api/stream/{job_id}/chapter/{affected0[0]}")
    assert r.status_code == 302, (
        "prior audio must stay playable throughout a rerender"
    )

    assert process_one("p15-rerender") is True
    with session_scope() as s:
        job = s.get(m.Job, job_id)
        assert job.status == m.JobStatus.succeeded, job.error
        after = _chapter_state(s, job_id)
        usage_after = _usage(s, api.org_id)

        # The money metric: exactly the affected chapters were re-billed.
        assert usage_after - usage_before == len(NGUYEN_CHAPTERS), (
            f"only chapters {sorted(NGUYEN_CHAPTERS)} may bill again; "
            f"delta was {usage_after - usage_before}"
        )

        for idx in range(20):
            sha_b, active_b, revs_b = before[idx]
            sha_a, active_a, revs_a = after[idx]
            if idx in affected0:
                assert sha_a != sha_b, f"chapter {idx} audio must change"
                assert active_a != active_b, f"chapter {idx} must get a new revision"
                assert [n for n, _ in revs_a] == [1, 2]
                assert dict(revs_a)[1] == "superseded"
                assert dict(revs_a)[2] == "active"
                new_rev = next(r for r in s.get(m.Job, job_id).chapters
                               if r.index == idx).revisions[-1]
                assert "NWIN" in new_rev.source_text
                assert "Nguyen" not in new_rev.source_text
            else:
                assert sha_a == sha_b, f"chapter {idx} audio must be untouched"
                assert active_a == active_b
                assert [n for n, _ in revs_a] == [1]


def test_forced_single_chapter_rerender_creates_revision(engine, api):
    api.signup("p15-force@example.com")
    text = ("Chapter 1: Alpha\n\n" + BODY + " Ending one. "
            + "\n\nChapter 2: Beta\n\n" + BODY + " Ending two. ")
    r = api.post("/api/synthesize", json={
        "text": text, "provider": "fake-paid", "voice_id": "fake-a",
        "engine": "neural", "formats": ["mp3"],
    })
    job_id = r.get_json()["task_id"]
    assert process_one("p15-force-1") is True

    with session_scope() as s:
        job = s.get(m.Job, job_id)
        assert job.status == m.JobStatus.succeeded, job.error
        target = next(c for c in job.chapters if c.index == 0)
        chapter_id, sha_before = target.id, target.audio_sha256
        usage_before = _usage(s, api.org_id)

    r = api.post(f"/api/chapters/{chapter_id}/rerender")
    assert r.status_code == 202, r.get_json()

    # Prior audio playable while queued for rerender.
    assert api.get(f"/api/stream/{job_id}/chapter/0").status_code == 302

    assert process_one("p15-force-2") is True
    with session_scope() as s:
        job = s.get(m.Job, job_id)
        assert job.status == m.JobStatus.succeeded, job.error
        target = next(c for c in job.chapters if c.index == 0)
        other = next(c for c in job.chapters if c.index == 1)
        # Forced rerender with unchanged text: new revision, byte-identical
        # audio (determinism), and no new billing — the chunk cache hit.
        assert [r.revision_number for r in target.revisions] == [1, 2]
        assert target.audio_sha256 == sha_before
        assert [r.revision_number for r in other.revisions] == [1]
        assert _usage(s, api.org_id) == usage_before, (
            "a forced rerender of unchanged text must not re-bill (cache hit)"
        )
