"""P1.3 gate: a voice assignment or lexicon edit demonstrably changes the
produced audio, proven by diffing output checksums.

Three proofs, all through real synthesis (fake provider, real assembly):
  1. lexicon edit → chapter audio checksum changes (default worker path);
  2. narrator voice assignment (voice_version_id) → checksum changes;
  3. per-character cast assignment → checksum changes for dialogue text.

Determinism control: two identical jobs with no lexicon produce identical
chapter checksums — so a checksum diff means the edit, not noise.
"""
import shutil

import pytest
from sqlalchemy import select

from db.base import utcnow
from db.session import session_scope
from db import models as m
from db.voice_models import VoiceCityVoiceVersion
from db.voxengine_models import PronunciationLexicon
from jobs import queue as q
from services.voice_city.direction_engine import normalize_character_name
from worker import process_one

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe required",
)

LEX_TEXT = ("Chapter 1: Names\n\n"
            + "Doctor Nguyen crossed the ward and greeted Doctor Nguyen's students warmly. " * 8)

NARRATION_TEXT = ("Chapter 1: Journey\n\n"
                  + "The road narrowed as the valley climbed toward the pass. " * 10)

DIALOGUE_TEXT = ("Chapter 1: The Pass\n\n"
                 + '"We should rest now before the climb," said Marla. '
                   "The trail wound higher through the pines and thinning air. " * 8)


def _seed_job(session, source_text):
    org = m.Organization(name="Org")
    user = m.User(email=f"a{utcnow().timestamp()}@x.com", password_hash="h")
    session.add_all([org, user])
    session.flush()
    session.add(m.Membership(user_id=user.id, organization_id=org.id, role=m.Role.owner))
    proj = m.Project(organization_id=org.id, created_by=user.id, title="B",
                     source_text=source_text)
    session.add(proj)
    session.flush()
    job = m.Job(organization_id=org.id, project_id=proj.id, provider="fake",
                voice_id="fake-a", formats="mp3")
    q.enqueue_job(session, job)
    return job.id, proj.id


def _run_and_sha(jid, worker):
    assert process_one(worker) is True
    with session_scope() as s:
        job = s.get(m.Job, jid)
        assert job.status == m.JobStatus.succeeded, job.error
        rows = sorted(job.chapters, key=lambda c: c.index)
        assert rows and all(c.audio_sha256 for c in rows)
        return tuple(c.audio_sha256 for c in rows)


# --------------------------------------------------------------------------- #
# 1. Lexicon edit changes the audio
# --------------------------------------------------------------------------- #

def test_lexicon_edit_changes_audio_checksum(engine):
    with session_scope() as s:
        jid_a, _ = _seed_job(s, LEX_TEXT)
    sha_a = _run_and_sha(jid_a, "p13-lex-a")

    # Determinism control: identical job, no lexicon → identical checksums.
    with session_scope() as s:
        jid_c, _ = _seed_job(s, LEX_TEXT)
    sha_c = _run_and_sha(jid_c, "p13-lex-c")
    assert sha_c == sha_a, "identical inputs must give identical audio (control)"

    # Lexicon edit on a fresh project: Nguyen → NWIN.
    with session_scope() as s:
        jid_b, proj_b = _seed_job(s, LEX_TEXT)
        s.add(PronunciationLexicon(project_id=proj_b, word="Nguyen",
                                   phonetic_spelling="NWIN"))
    sha_b = _run_and_sha(jid_b, "p13-lex-b")
    assert sha_b != sha_a, (
        "a lexicon edit must audibly change the produced chapter audio"
    )


# --------------------------------------------------------------------------- #
# Voice City fixtures for assignment proofs
# --------------------------------------------------------------------------- #

def _make_fake_versions(client, headers, count, voice_ids):
    """Generate+accept Voice City voices, then point their current versions
    at the fake provider so synthesis is offline and deterministic."""
    gen = client.post("/api/voice-city/generate", headers=headers, json={
        "description": "clear neutral adult narrator, steady pace",
        "count": count, "seed": 20260812,
    })
    assert gen.status_code in (200, 201), gen.get_json()
    candidates = gen.get_json()["candidates"]
    version_ids = []
    for idx, cand in enumerate(candidates[:count]):
        acc = client.post(f"/api/voice-city/candidates/{cand['id']}/accept",
                          headers=headers, json={"name": f"P13 Voice {idx}"})
        assert acc.status_code in (200, 201), acc.get_json()
        body = acc.get_json()
        voice_id = body["voice"]["id"] if "voice" in body else body["id"]
        detail = client.get(f"/api/voice-city/voices/{voice_id}", headers=headers).get_json()
        version_ids.append(detail["current_version"]["id"])
    with session_scope() as s:
        for vid, fake_voice in zip(version_ids, voice_ids):
            v = s.get(VoiceCityVoiceVersion, vid)
            v.provider = "fake"
            v.provider_voice_id = fake_voice
            v.status = "ready"
    return version_ids


def _synthesize_via_api(client, headers, text, voice_version_id, voice_direction=None):
    payload = {
        "text": text, "provider": "fake", "voice_id": "fake-a",
        "engine": "neural", "formats": ["mp3"],
        "voice_version_id": voice_version_id,
    }
    if voice_direction is not None:
        payload["voice_direction"] = voice_direction
    r = client.post("/api/synthesize", headers=headers, json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["task_id"]


# --------------------------------------------------------------------------- #
# 2. Narrator voice assignment changes the audio
# --------------------------------------------------------------------------- #

def test_narrator_voice_assignment_changes_audio(engine, client, auth_headers):
    headers, _org = auth_headers("p13-narrator@x.com")
    v1, v2 = _make_fake_versions(client, headers, 2, ["fake-a", "fake-b"])

    jid_a = _synthesize_via_api(client, headers, NARRATION_TEXT, v1)
    sha_a = _run_and_sha(jid_a, "p13-nar-a")
    jid_b = _synthesize_via_api(client, headers, NARRATION_TEXT, v2)
    sha_b = _run_and_sha(jid_b, "p13-nar-b")

    assert sha_a != sha_b, (
        "assigning a different narrator voice must change the produced audio"
    )


# --------------------------------------------------------------------------- #
# 3. Per-character cast assignment changes the audio
# --------------------------------------------------------------------------- #

def test_cast_assignment_changes_dialogue_audio(engine, client, auth_headers):
    headers, _org = auth_headers("p13-cast@x.com")
    v0, v1, v2 = _make_fake_versions(client, headers, 3,
                                     ["fake-a", "fake-a", "fake-b"])

    def direction(marla_version):
        return {
            "enabled": True,
            "automatic_dialogue_detection": True,
            "cast": [{
                "character_name": "Marla",
                "normalized_name": normalize_character_name("Marla"),
                "voice_version_id": marla_version,
            }],
        }

    jid_a = _synthesize_via_api(client, headers, DIALOGUE_TEXT, v0,
                                voice_direction=direction(v1))
    sha_a = _run_and_sha(jid_a, "p13-cast-a")
    jid_b = _synthesize_via_api(client, headers, DIALOGUE_TEXT, v0,
                                voice_direction=direction(v2))
    sha_b = _run_and_sha(jid_b, "p13-cast-b")

    assert sha_a != sha_b, (
        "recasting a character to a different voice must change the produced "
        "audio for chapters containing that character's dialogue"
    )
