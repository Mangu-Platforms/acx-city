"""Flask blueprint: VoxEngine routes migrated from the FastAPI /v1 sidecar.

All routes are on /api/... (Flask's canonical surface), authenticated via
require_auth / current_identity(), and org-scoped via resolve_org().

Replaces backend/v1_api.py (FastAPI + Uvicorn sidecar, not deployed).
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, g, jsonify, redirect, request
from sqlalchemy import select

from auth import current_identity, require_auth
from auth.guard import resolve_org
from db.models import ChapterResult, Job, Project
from db.voxengine_models import (
    CharacterVoiceMap,
    PipelineTrace,
    PronunciationLexicon,
    StockVoice,
    VoiceClone,
)

log = logging.getLogger("acx.voxengine")

voxengine_bp = Blueprint("voxengine", __name__, url_prefix="/api")


def _owned_project(project_id: str) -> Project:
    """Return the Project if the authenticated org owns it, else 404."""
    identity = current_identity()
    project = g.db.get(Project, project_id)
    if not project or project.organization_id != identity.org.id:
        from flask import abort
        abort(404)
    return project


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

@voxengine_bp.route("/projects/<project_id>/characters", methods=["GET"])
@require_auth
def list_characters(project_id: str):
    _owned_project(project_id)
    chars = g.db.execute(
        select(CharacterVoiceMap)
        .where(CharacterVoiceMap.project_id == project_id)
        .order_by(CharacterVoiceMap.is_narrator.desc(), CharacterVoiceMap.character_name)
    ).scalars().all()
    return jsonify([
        {
            "id": c.id,
            "character_name": c.character_name,
            "voice_id": c.voice_id,
            "voice_slug": c.voice_slug,
            "pitch_adjustment": float(c.pitch_adjustment or 1.0),
            "speed_adjustment": float(c.speed_adjustment or 1.0),
            "base_emotion": c.base_emotion,
            "is_narrator": c.is_narrator,
            "attribution_confidence": c.attribution_confidence,
            "notes": c.notes,
        }
        for c in chars
    ])


@voxengine_bp.route("/projects/<project_id>/characters", methods=["POST"])
@require_auth
def set_character(project_id: str):
    _owned_project(project_id)
    data = request.get_json(silent=True) or {}
    name = data.get("character_name")
    if not name:
        return jsonify({"error": "character_name required"}), 400

    existing = g.db.execute(
        select(CharacterVoiceMap)
        .where(CharacterVoiceMap.project_id == project_id)
        .where(CharacterVoiceMap.character_name == name)
    ).scalar_one_or_none()

    if existing:
        for field in ("voice_id", "voice_slug", "pitch_adjustment", "speed_adjustment",
                      "base_emotion", "is_narrator", "notes"):
            if field in data:
                setattr(existing, field, data[field])
        g.db.commit()
        return jsonify({"id": existing.id, "updated": True})

    char = CharacterVoiceMap(
        project_id=project_id,
        character_name=name,
        voice_id=data.get("voice_id"),
        voice_slug=data.get("voice_slug"),
        pitch_adjustment=data.get("pitch_adjustment", 1.0),
        speed_adjustment=data.get("speed_adjustment", 1.0),
        base_emotion=data.get("base_emotion", "neutral"),
        is_narrator=data.get("is_narrator", False),
        notes=data.get("notes"),
    )
    g.db.add(char)
    g.db.commit()
    return jsonify({"id": char.id, "created": True}), 201


# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------

@voxengine_bp.route("/projects/<project_id>/lexicon", methods=["GET"])
@require_auth
def list_lexicon(project_id: str):
    _owned_project(project_id)
    entries = g.db.execute(
        select(PronunciationLexicon)
        .where(PronunciationLexicon.project_id == project_id)
        .order_by(PronunciationLexicon.word)
    ).scalars().all()
    return jsonify([
        {
            "id": e.id,
            "word": e.word,
            "ipa_phoneme": e.ipa_phoneme,
            "phonetic_spelling": e.phonetic_spelling,
            "context_note": e.context_note,
            "source": e.source,
            "is_global": e.is_global,
        }
        for e in entries
    ])


@voxengine_bp.route("/projects/<project_id>/lexicon", methods=["POST"])
@require_auth
def add_lexicon_entry(project_id: str):
    _owned_project(project_id)
    data = request.get_json(silent=True) or {}
    word = data.get("word")
    if not word:
        return jsonify({"error": "word required"}), 400

    existing = g.db.execute(
        select(PronunciationLexicon)
        .where(PronunciationLexicon.project_id == project_id)
        .where(PronunciationLexicon.word == word)
    ).scalar_one_or_none()

    if existing:
        for field in ("ipa_phoneme", "phonetic_spelling", "context_note", "is_global"):
            if field in data:
                setattr(existing, field, data[field])
        g.db.commit()
        return jsonify({"id": existing.id, "updated": True})

    entry = PronunciationLexicon(
        project_id=project_id,
        word=word,
        ipa_phoneme=data.get("ipa_phoneme"),
        phonetic_spelling=data.get("phonetic_spelling"),
        context_note=data.get("context_note"),
        source="manual",
        is_global=data.get("is_global", False),
    )
    g.db.add(entry)
    g.db.commit()
    return jsonify({"id": entry.id, "created": True}), 201


@voxengine_bp.route("/projects/<project_id>/lexicon/<entry_id>", methods=["DELETE"])
@require_auth
def delete_lexicon_entry(project_id: str, entry_id: str):
    _owned_project(project_id)
    entry = g.db.get(PronunciationLexicon, entry_id)
    if not entry or entry.project_id != project_id:
        return jsonify({"error": "Entry not found"}), 404
    g.db.delete(entry)
    g.db.commit()
    return jsonify({"deleted": True})


# ---------------------------------------------------------------------------
# Pipeline status (read-only — start still requires multi-agent worker, P1.2)
# ---------------------------------------------------------------------------

@voxengine_bp.route("/projects/<project_id>/pipeline/status", methods=["GET"])
@require_auth
def pipeline_status(project_id: str):
    _owned_project(project_id)
    job = g.db.execute(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not job:
        return jsonify({"error": "No job found for this project"}), 404

    traces = g.db.execute(
        select(PipelineTrace)
        .where(PipelineTrace.job_id == job.id)
        .order_by(PipelineTrace.chapter_number)
    ).scalars().all()

    completed = sum(1 for t in traces if t.status == "completed")
    failed = sum(1 for t in traces if t.status == "failed")
    total_cost = sum(
        float(t.agent2_cost_usd or 0) + float(t.agent3_cost_usd or 0) +
        float(t.agent4_cost_usd or 0) + float(t.agent5_cost_usd or 0)
        for t in traces
    )

    return jsonify({
        "job_id": job.id,
        "status": job.status.value,
        "chapters_total": len(traces),
        "chapters_completed": completed,
        "chapters_failed": failed,
        "total_cost_usd": round(total_cost, 6),
        "traces": [
            {
                "chapter_number": t.chapter_number,
                "status": t.status,
                "current_agent": t.current_agent,
                "agent1_ms": t.agent1_ms,
                "agent2_ms": t.agent2_ms,
                "agent3_ms": t.agent3_ms,
                "agent4_ms": t.agent4_ms,
                "agent5_ms": t.agent5_ms,
                "qa_passed": t.qa_passed,
                "qa_completeness_score": t.qa_completeness_score,
                "error": t.error,
            }
            for t in traces
        ],
    })


@voxengine_bp.route("/projects/<project_id>/pipeline/trace/<int:chapter_number>", methods=["GET"])
@require_auth
def pipeline_trace(project_id: str, chapter_number: int):
    _owned_project(project_id)
    job = g.db.execute(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not job:
        return jsonify({"error": "No job found"}), 404

    trace = g.db.execute(
        select(PipelineTrace)
        .where(PipelineTrace.job_id == job.id)
        .where(PipelineTrace.chapter_number == chapter_number)
    ).scalar_one_or_none()

    if not trace:
        return jsonify({"error": f"No trace for chapter {chapter_number}"}), 404

    return jsonify({
        "id": trace.id,
        "job_id": trace.job_id,
        "chapter_number": trace.chapter_number,
        "status": trace.status,
        "current_agent": trace.current_agent,
        "agents": {
            "structure_parser": {"ms": trace.agent1_ms},
            "character_attribution": {"ms": trace.agent2_ms, "cost_usd": float(trace.agent2_cost_usd or 0)},
            "text_normalizer": {"ms": trace.agent3_ms, "cost_usd": float(trace.agent3_cost_usd or 0)},
            "prosody_planner": {"ms": trace.agent4_ms, "cost_usd": float(trace.agent4_cost_usd or 0)},
            "qa_validator": {"ms": trace.agent5_ms, "cost_usd": float(trace.agent5_cost_usd or 0)},
        },
        "characters_in": trace.characters_in,
        "characters_out": trace.characters_out,
        "qa_passed": trace.qa_passed,
        "qa_issues": trace.qa_issues,
        "qa_completeness_score": trace.qa_completeness_score,
        "error": trace.error,
    })


@voxengine_bp.route("/projects/<project_id>/pipeline/start", methods=["POST"])
@require_auth
def start_pipeline(project_id: str):
    """Multi-agent pipeline start — requires Celery worker (P1.2). Not yet deployed."""
    _owned_project(project_id)
    return jsonify({
        "error": "Multi-agent pipeline is disabled (PIPELINE_ENABLED=false). "
                 "Enable after P1.2 when the pipeline runs through worker.py."
    }), 503


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

@voxengine_bp.route("/voices", methods=["GET"])
@require_auth
def list_voices():
    provider = request.args.get("provider")
    gender = request.args.get("gender")
    accent = request.args.get("accent")
    is_active = request.args.get("is_active", "true").lower() != "false"
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    query = select(StockVoice).where(StockVoice.is_active == is_active)
    if provider:
        query = query.where(StockVoice.provider == provider)
    if gender:
        query = query.where(StockVoice.gender == gender)
    if accent:
        query = query.where(StockVoice.accent == accent)
    query = query.order_by(StockVoice.display_name).offset(offset).limit(limit)

    voices = g.db.execute(query).scalars().all()
    return jsonify([
        {
            "id": v.id,
            "slug": v.slug,
            "display_name": v.display_name,
            "gender": v.gender,
            "accent": v.accent,
            "age_range": v.age_range,
            "style_tags": v.style_tags,
            "description": v.description,
            "provider": v.provider,
            "sample_url": v.sample_audio_url,
            "languages": v.languages,
            "emotion_tags": v.emotion_tags,
            "is_cloneable": v.is_cloneable,
        }
        for v in voices
    ])


@voxengine_bp.route("/voices/clones", methods=["GET"])
@require_auth
def list_voice_clones():
    identity = current_identity()
    clones = g.db.execute(
        select(VoiceClone)
        .where(VoiceClone.organization_id == identity.org.id)
        .order_by(VoiceClone.created_at.desc())
    ).scalars().all()
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "provider": c.provider,
            "reference_duration_seconds": float(c.reference_duration_seconds or 0),
            "safety_similarity_score": c.safety_similarity_score,
            "created_at": c.created_at.isoformat(),
        }
        for c in clones
    ])


@voxengine_bp.route("/voices/clone", methods=["POST"])
@require_auth
def create_voice_clone():
    """Voice cloning not yet implemented — hide behind flag at P2.1."""
    return jsonify({"error": "Voice cloning not yet implemented"}), 501


@voxengine_bp.route("/voices/<voice_id>", methods=["GET"])
@require_auth
def get_voice(voice_id: str):
    voice = g.db.get(StockVoice, voice_id)
    if not voice:
        return jsonify({"error": "Voice not found"}), 404
    return jsonify({
        "id": voice.id,
        "slug": voice.slug,
        "display_name": voice.display_name,
        "gender": voice.gender,
        "accent": voice.accent,
        "age_range": voice.age_range,
        "style_tags": voice.style_tags,
        "description": voice.description,
        "provider": voice.provider,
        "provider_voice_id": voice.provider_voice_id,
        "sample_url": voice.sample_audio_url,
        "languages": voice.languages,
        "emotion_tags": voice.emotion_tags,
        "is_cloneable": voice.is_cloneable,
        "source": voice.source,
    })


@voxengine_bp.route("/voices/<voice_id>/sample", methods=["GET"])
@require_auth
def get_voice_sample(voice_id: str):
    """Return a short audio sample for a voice.

    If the voice has a pre-recorded `sample_audio_url`, redirects there (302).
    Otherwise synthesises "Hello, I'm [name]." on the fly using the voice's
    provider and returns audio/mpeg bytes directly.
    """
    voice = g.db.get(StockVoice, voice_id)
    if not voice:
        return jsonify({"error": "Voice not found"}), 404

    if voice.sample_audio_url:
        return redirect(voice.sample_audio_url, code=302)

    # On-demand synthesis fallback.
    from services.providers.registry import ProviderRegistry
    registry = ProviderRegistry()
    provider = registry.get(voice.provider)
    if provider is None or not provider.is_available():
        return jsonify({"error": f"Provider '{voice.provider}' not available"}), 503

    sample_text = f"Hello, I'm {voice.display_name}. I'd love to narrate your audiobook."
    try:
        provider_voice_id = voice.provider_voice_id or voice.slug
        audio_bytes = provider.synthesize(sample_text, provider_voice_id)
        return Response(
            audio_bytes,
            content_type="audio/mpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as exc:
        log.warning("voice sample synthesis failed for %s: %s", voice_id, exc)
        return jsonify({"error": "Sample synthesis failed"}), 500


# ---------------------------------------------------------------------------
# Chapters — rerender + waveform
# ---------------------------------------------------------------------------

@voxengine_bp.route("/chapters/<chapter_id>/rerender", methods=["POST"])
@require_auth
def rerender_chapter(chapter_id: str):
    """Chapter rerender — requires Celery worker (P1.5). Not yet deployed."""
    identity = current_identity()
    chapter = g.db.get(ChapterResult, chapter_id)
    if not chapter:
        return jsonify({"error": "Chapter not found"}), 404
    job = g.db.get(Job, chapter.job_id)
    if not job or job.organization_id != identity.org.id:
        return jsonify({"error": "Chapter not found"}), 404
    return jsonify({
        "error": "Chapter rerender requires the Celery worker (P1.5, not yet deployed). "
                 "Use the full job pipeline for now."
    }), 503


@voxengine_bp.route("/chapters/<chapter_id>/waveform", methods=["GET"])
@require_auth
def get_waveform(chapter_id: str):
    """Waveform stub — peaks to be pre-computed at P1.6."""
    identity = current_identity()
    chapter = g.db.get(ChapterResult, chapter_id)
    if not chapter:
        return jsonify({"error": "Chapter not found"}), 404
    job = g.db.get(Job, chapter.job_id)
    if not job or job.organization_id != identity.org.id:
        return jsonify({"error": "Chapter not found"}), 404
    return jsonify({
        "chapter_id": chapter_id,
        "duration_s": chapter.duration_s,
        "sample_rate": 24000,
        "peaks": [],
        "markers": [],
    })
