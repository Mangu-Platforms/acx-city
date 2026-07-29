"""Authenticated, organization-scoped Voice City HTTP API."""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Mapping

from flask import Blueprint, g, jsonify, request

from auth import current_identity, require_auth
from db.voice_models import (
    VoiceCityCandidate,
    VoiceCityCandidateSet,
    VoiceCityPreview,
)
from services.voice_city.audition_scripts import AUDITION_SCRIPTS, get_audition_script
from services.voice_city.direction_engine import analyze_dialogue, validate_direction_plan
from services.voice_city.parameter_schema import ParameterValidationError, schema_document
from services.voice_city.preview_renderer import PreviewError, PreviewRenderer
from services.voice_city.service import VoiceCityError, VoiceCityService, serialize_candidate
from storage import get_storage

voice_city_bp = Blueprint("voice_city", __name__, url_prefix="/api/voice-city")
_preview_renderer = PreviewRenderer()


def _service() -> VoiceCityService:
    identity = current_identity()
    return VoiceCityService(
        g.db,
        organization_id=identity.org.id,
        user_id=identity.user.id,
    )


def _body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _commit(payload: Any, status: int = 200):
    g.db.commit()
    return jsonify(payload), status


@voice_city_bp.errorhandler(ValueError)
@voice_city_bp.errorhandler(VoiceCityError)
@voice_city_bp.errorhandler(ParameterValidationError)
@voice_city_bp.errorhandler(PreviewError)
def _voice_city_error(exc):
    g.db.rollback()
    return jsonify({"error": str(exc)}), 400


@voice_city_bp.route("/capabilities", methods=["GET"])
@require_auth
def capabilities():
    return jsonify(_service().capabilities())


@voice_city_bp.route("/schema", methods=["GET"])
@require_auth
def parameter_schema():
    mode = request.args.get("mode", "laboratory")
    search = request.args.get("search")
    return jsonify(schema_document(mode=mode, search=search))


@voice_city_bp.route("/audition-scripts", methods=["GET"])
@require_auth
def audition_scripts():
    category = request.args.get("category")
    scripts = [script for script in AUDITION_SCRIPTS if not category or script["category"] == category]
    return jsonify(scripts)


# ---------------------------------------------------------------------------
# Character direction and dialogue analysis
# ---------------------------------------------------------------------------
@voice_city_bp.route("/direction/analyze", methods=["POST"])
@require_auth
def analyze_direction():
    data = _body()
    text = str(data.get("text") or "")
    if not text.strip():
        raise VoiceCityError("Manuscript text is required")
    return jsonify(analyze_dialogue(text))


@voice_city_bp.route("/direction/validate", methods=["POST"])
@require_auth
def validate_direction():
    data = _body()
    plan = validate_direction_plan(
        data.get("plan") or {},
        seed=int(data.get("seed", 481928)),
    )
    return jsonify(plan)


# ---------------------------------------------------------------------------
# Voices and versions
# ---------------------------------------------------------------------------
@voice_city_bp.route("/voices", methods=["GET"])
@require_auth
def list_voices():
    return jsonify(_service().list_voices(status=request.args.get("status")))


@voice_city_bp.route("/voices", methods=["POST"])
@require_auth
def create_voice():
    data = _body()
    result = _service().create_voice(
        name=data.get("name", ""),
        description=data.get("description"),
        parameters=data.get("parameters"),
        seed=int(data.get("seed", 481928)),
        provider=data.get("provider", "edge"),
        provider_voice_id=data.get("provider_voice_id"),
        tags=data.get("tags") or [],
        default_use_cases=data.get("default_use_cases") or [],
    )
    return _commit(result, 201)


@voice_city_bp.route("/voices/<voice_id>", methods=["GET"])
@require_auth
def get_voice(voice_id: str):
    return jsonify(_service().get_voice(voice_id))


@voice_city_bp.route("/voices/<voice_id>", methods=["PATCH"])
@require_auth
def update_voice(voice_id: str):
    data = _body()
    result = _service().update_voice_metadata(
        voice_id,
        name=data.get("name") if "name" in data else None,
        description=data.get("description") if "description" in data else None,
        tags=data.get("tags") if "tags" in data else None,
        default_use_cases=data.get("default_use_cases") if "default_use_cases" in data else None,
        visibility=data.get("visibility") if "visibility" in data else None,
    )
    return _commit(result)


@voice_city_bp.route("/voices/<voice_id>", methods=["DELETE"])
@require_auth
def delete_voice(voice_id: str):
    _service().delete_voice(voice_id)
    return _commit({"voice_id": voice_id, "deleted": True})


@voice_city_bp.route("/voices/<voice_id>/versions", methods=["POST"])
@require_auth
def save_version(voice_id: str):
    data = _body()
    result = _service().save_version(
        voice_id,
        parameters=data.get("parameters") or {},
        change_note=data.get("change_note"),
        provider_voice_id=data.get("provider_voice_id"),
        expected_current_version_id=data.get("expected_current_version_id"),
    )
    return _commit(result, 201)


@voice_city_bp.route("/voices/<voice_id>/rollback", methods=["POST"])
@require_auth
def rollback_voice(voice_id: str):
    data = _body()
    result = _service().rollback(voice_id, str(data.get("version_id") or ""))
    return _commit(result)


@voice_city_bp.route("/voices/<voice_id>/revoke", methods=["POST"])
@require_auth
def revoke_voice(voice_id: str):
    result = _service().revoke_voice(voice_id, reason=_body().get("reason"))
    return _commit(result)


@voice_city_bp.route("/voices/<voice_id>/export", methods=["GET"])
@require_auth
def export_voice_recipe(voice_id: str):
    result = _service().export_recipe(voice_id, version_id=request.args.get("version_id"))
    return _commit(result)


# ---------------------------------------------------------------------------
# Generate, mutate, breed, compare, accept/reject
# ---------------------------------------------------------------------------
@voice_city_bp.route("/generate", methods=["POST"])
@require_auth
def generate_variants():
    data = _body()
    result = _service().generate(
        description=str(data.get("description") or ""),
        provider=data.get("provider", "edge"),
        count=int(data.get("count", 4)),
        seed=int(data.get("seed", 481928)),
        locked_paths=data.get("locked_paths") or [],
    )
    return _commit(result, 201)


@voice_city_bp.route("/versions/<version_id>/mutate", methods=["POST"])
@require_auth
def mutate_version(version_id: str):
    data = _body()
    result = _service().mutate(
        version_id,
        request_text=str(data.get("request") or ""),
        seed=int(data["seed"]) if data.get("seed") is not None else None,
        locked_paths=data.get("locked_paths") or [],
    )
    return _commit(result, 201)


@voice_city_bp.route("/versions/<version_id>/optimize", methods=["POST"])
@require_auth
def optimize_version(version_id: str):
    result = _service().optimize_version(version_id)
    return _commit(result, 202)


@voice_city_bp.route("/breed", methods=["POST"])
@require_auth
def breed_voices():
    data = _body()
    result = _service().breed(
        str(data.get("version_a_id") or ""),
        str(data.get("version_b_id") or ""),
        weight_a=float(data.get("weight_a", 0.7)),
        seed=int(data.get("seed", 481928)),
        locked_from_a=data.get("locked_from_a") or [],
    )
    return _commit(result, 201)


@voice_city_bp.route("/candidate-sets/<candidate_set_id>", methods=["GET"])
@require_auth
def candidate_set(candidate_set_id: str):
    return jsonify(_service().list_candidates(candidate_set_id))


@voice_city_bp.route("/candidates/<candidate_id>", methods=["GET"])
@require_auth
def get_candidate(candidate_id: str):
    _set, candidate = _service()._get_candidate(candidate_id)
    return jsonify(serialize_candidate(candidate))


@voice_city_bp.route("/candidates/compare", methods=["POST"])
@require_auth
def compare_candidates():
    result = _service().compare_candidates(_body().get("candidate_ids") or [])
    return jsonify(result)


@voice_city_bp.route("/candidates/<candidate_id>/accept", methods=["POST"])
@require_auth
def accept_candidate(candidate_id: str):
    data = _body()
    result = _service().accept_candidate(
        candidate_id,
        voice_id=data.get("voice_id"),
        name=data.get("name"),
        change_note=data.get("change_note"),
    )
    return _commit(result, 201)


@voice_city_bp.route("/candidates/<candidate_id>/reject", methods=["POST"])
@require_auth
def reject_candidate(candidate_id: str):
    result = _service().reject_candidate(candidate_id, reason=_body().get("reason"))
    return _commit(result)


@voice_city_bp.route("/generation-jobs/<job_id>", methods=["GET"])
@require_auth
def generation_job(job_id: str):
    return jsonify(_service().get_generation_job(job_id))


@voice_city_bp.route("/generation-jobs/<job_id>/cancel", methods=["POST"])
@require_auth
def cancel_generation_job(job_id: str):
    return _commit(_service().cancel_generation_job(job_id), 202)


# ---------------------------------------------------------------------------
# Audition room: preview, A/B/blind comparison, sentence segmentation
# ---------------------------------------------------------------------------
def _resolve_preview_source(service: VoiceCityService, data: Mapping[str, Any]):
    version_id = data.get("voice_version_id")
    candidate_id = data.get("candidate_id")
    if bool(version_id) == bool(candidate_id):
        raise VoiceCityError("Provide exactly one of voice_version_id or candidate_id")
    if version_id:
        voice, version = service._get_version(str(version_id))
        parameters = version.canonical_parameters
        provider = version.provider
        provider_voice_id = version.provider_voice_id
        voice_id = voice.id
        model_revision = version.model_revision
        rules = service.list_pronunciation_rules(voice_id=voice.id)
        return {
            "parameters": parameters,
            "provider": provider,
            "provider_voice_id": provider_voice_id,
            "voice_id": voice_id,
            "voice_version_id": version.id,
            "candidate_id": None,
            "model_revision": model_revision,
            "rules": rules,
            "display_name": f"{voice.name} V{version.version_number}",
        }
    _set, candidate = service._get_candidate(str(candidate_id))
    return {
        "parameters": candidate.canonical_parameters,
        "provider": candidate.provider,
        "provider_voice_id": candidate.provider_voice_id,
        "voice_id": None,
        "voice_version_id": None,
        "candidate_id": candidate.id,
        "model_revision": "candidate-catalog-v1",
        "rules": service.list_pronunciation_rules(),
        "display_name": candidate.name,
    }


def _preview_text(data: Mapping[str, Any]) -> tuple[str, str | None]:
    script_id = data.get("script_id")
    script = get_audition_script(str(script_id)) if script_id else None
    text = str(data.get("text") or (script["text"] if script else ""))
    return text, str(script_id) if script_id else None


@voice_city_bp.route("/previews", methods=["POST"])
@require_auth
def create_preview():
    data = _body()
    service = _service()
    source = _resolve_preview_source(service, data)
    text, script_id = _preview_text(data)
    preview, result = _preview_renderer.render(
        g.db,
        organization_id=current_identity().org.id,
        user_id=current_identity().user.id,
        parameters=source["parameters"],
        provider=source["provider"],
        provider_voice_id=source["provider_voice_id"],
        text=text,
        voice_id=source["voice_id"],
        voice_version_id=source["voice_version_id"],
        candidate_id=source["candidate_id"],
        script_id=script_id,
        overrides=data.get("overrides") or {},
        pronunciation_rules=source["rules"],
        engine=data.get("engine", "neural"),
        model_revision=source["model_revision"],
        loudness_match=bool(data.get("loudness_match", True)),
    )
    service._audit(
        "preview.rendered",
        subject_type="preview",
        subject_id=preview.id,
        voice_id=source["voice_id"],
        payload={"script_id": script_id, "candidate_id": source["candidate_id"]},
    )
    return _commit(
        {
            "id": preview.id,
            "status": preview.status,
            "duration_s": preview.duration_s,
            "display_name": source["display_name"],
            **result,
        },
        201,
    )


@voice_city_bp.route("/previews", methods=["GET"])
@require_auth
def list_previews():
    identity = current_identity()
    query = g.db.query(VoiceCityPreview).filter(VoiceCityPreview.organization_id == identity.org.id)
    if request.args.get("voice_version_id"):
        query = query.filter(VoiceCityPreview.voice_version_id == request.args["voice_version_id"])
    rows = query.order_by(VoiceCityPreview.created_at.desc()).limit(100).all()
    return jsonify(
        [
            {
                "id": row.id,
                "voice_version_id": row.voice_version_id,
                "candidate_id": row.candidate_id,
                "script_id": row.script_id,
                "text": row.text,
                "provider": row.provider,
                "provider_voice_id": row.provider_voice_id,
                "duration_s": row.duration_s,
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    )


@voice_city_bp.route("/previews/<preview_id>/url", methods=["GET"])
@require_auth
def preview_url(preview_id: str):
    identity = current_identity()
    preview = g.db.get(VoiceCityPreview, preview_id)
    if preview is None or preview.organization_id != identity.org.id or not preview.audio_key:
        raise VoiceCityError("Preview not found")
    signed = get_storage().signed_url(
        preview.audio_key,
        expires_in=int(request.args.get("expires_in", 3600)),
        download_name="voice-city-preview.mp3",
    )
    return jsonify({"url": signed.url, "expires_in": signed.expires_in})


@voice_city_bp.route("/previews/<preview_id>", methods=["DELETE"])
@require_auth
def delete_preview(preview_id: str):
    identity = current_identity()
    preview = g.db.get(VoiceCityPreview, preview_id)
    if preview is None or preview.organization_id != identity.org.id:
        raise VoiceCityError("Preview not found")
    storage = get_storage()
    if preview.audio_key:
        storage.delete(preview.audio_key)
    storage.delete(f"org/{identity.org.id}/voice-city/previews/{preview.id}/provenance.json")
    g.db.delete(preview)
    return _commit({"preview_id": preview_id, "deleted": True})


@voice_city_bp.route("/auditions/compare", methods=["POST"])
@require_auth
def compare_auditions():
    data = _body()
    sources = data.get("sources") or []
    if not 2 <= len(sources) <= 8:
        raise VoiceCityError("Compare between two and eight voice versions/candidates")
    text, script_id = _preview_text(data)
    if not text:
        raise VoiceCityError("Comparison text or script_id is required")
    segment_mode = data.get("segment_mode", "whole")
    if segment_mode not in {"whole", "sentence"}:
        raise VoiceCityError("segment_mode must be whole or sentence")
    segments = [text]
    if segment_mode == "sentence":
        import re

        segments = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()][:6]
    service = _service()
    rendered: list[dict[str, Any]] = []
    for source_index, source_data in enumerate(sources):
        source = _resolve_preview_source(service, source_data)
        source_previews = []
        for segment_index, segment in enumerate(segments):
            preview, result = _preview_renderer.render(
                g.db,
                organization_id=current_identity().org.id,
                user_id=current_identity().user.id,
                parameters=source["parameters"],
                provider=source["provider"],
                provider_voice_id=source["provider_voice_id"],
                text=segment,
                voice_id=source["voice_id"],
                voice_version_id=source["voice_version_id"],
                candidate_id=source["candidate_id"],
                script_id=script_id,
                overrides=source_data.get("overrides") or {},
                pronunciation_rules=source["rules"],
                engine=source_data.get("engine", "neural"),
                model_revision=source["model_revision"],
                loudness_match=True,
            )
            source_previews.append(
                {
                    "segment_index": segment_index,
                    "text": segment,
                    "preview_id": preview.id,
                    "duration_s": preview.duration_s,
                    **result,
                }
            )
        rendered.append(
            {
                "source_index": source_index,
                "display_name": source["display_name"],
                "voice_version_id": source["voice_version_id"],
                "candidate_id": source["candidate_id"],
                "previews": source_previews,
            }
        )

    blind = bool(data.get("blind", False))
    comparison_id = hashlib.sha256(
        json.dumps(
            {
                "sources": [item.get("voice_version_id") or item.get("candidate_id") for item in rendered],
                "text": text,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:20]
    reveal = []
    if blind:
        rng = random.Random(int(comparison_id[:8], 16))
        labels = [f"Sample {chr(65 + index)}" for index in range(len(rendered))]
        rng.shuffle(labels)
        for item, label in zip(rendered, labels):
            reveal.append({"label": label, "display_name": item["display_name"]})
            item["blind_label"] = label
            item.pop("display_name", None)
    return _commit(
        {
            "comparison_id": comparison_id,
            "blind": blind,
            "segment_mode": segment_mode,
            "sources": rendered,
            "reveal": reveal,
        },
        201,
    )


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
@voice_city_bp.route("/presets", methods=["GET"])
@require_auth
def list_presets():
    return jsonify(_service().list_presets())


@voice_city_bp.route("/presets", methods=["POST"])
@require_auth
def create_preset():
    data = _body()
    result = _service().create_preset(
        name=str(data.get("name") or ""),
        description=data.get("description"),
        category=data.get("category", "custom"),
        parameters=data.get("parameters") or {},
        source_voice_version_id=data.get("source_voice_version_id"),
    )
    return _commit(result, 201)


@voice_city_bp.route("/presets/<preset_id>", methods=["GET"])
@require_auth
def get_preset(preset_id: str):
    return jsonify(_service().resolve_preset(preset_id))


@voice_city_bp.route("/presets/<preset_id>", methods=["DELETE"])
@require_auth
def delete_preset(preset_id: str):
    _service().delete_preset(preset_id)
    return _commit({"preset_id": preset_id, "deleted": True})


# ---------------------------------------------------------------------------
# Pronunciation dictionary
# ---------------------------------------------------------------------------
@voice_city_bp.route("/pronunciations", methods=["GET"])
@require_auth
def list_pronunciations():
    return jsonify(_service().list_pronunciation_rules(voice_id=request.args.get("voice_id")))


@voice_city_bp.route("/pronunciations", methods=["POST"])
@require_auth
def create_pronunciation():
    return _commit(_service().create_pronunciation_rule(_body()), 201)


@voice_city_bp.route("/pronunciations/<rule_id>", methods=["PATCH"])
@require_auth
def update_pronunciation(rule_id: str):
    return _commit(_service().update_pronunciation_rule(rule_id, _body()))


@voice_city_bp.route("/pronunciations/<rule_id>", methods=["DELETE"])
@require_auth
def delete_pronunciation(rule_id: str):
    _service().delete_pronunciation_rule(rule_id)
    return _commit({"rule_id": rule_id, "deleted": True})


# ---------------------------------------------------------------------------
# Automation curves
# ---------------------------------------------------------------------------
@voice_city_bp.route("/voices/<voice_id>/automation", methods=["GET"])
@require_auth
def list_automation(voice_id: str):
    return jsonify(_service().list_automation_tracks(voice_id, project_id=request.args.get("project_id")))


@voice_city_bp.route("/voices/<voice_id>/automation", methods=["POST"])
@require_auth
def create_automation(voice_id: str):
    return _commit(_service().create_automation_track(voice_id, _body()), 201)


@voice_city_bp.route("/automation/<track_id>", methods=["PATCH"])
@require_auth
def update_automation(track_id: str):
    return _commit(_service().update_automation_track(track_id, _body()))


@voice_city_bp.route("/automation/<track_id>", methods=["DELETE"])
@require_auth
def delete_automation(track_id: str):
    _service().delete_automation_track(track_id)
    return _commit({"track_id": track_id, "deleted": True})


# ---------------------------------------------------------------------------
# Quality/readiness, audit, and future authorization metadata
# ---------------------------------------------------------------------------
@voice_city_bp.route("/versions/<version_id>/quality", methods=["GET"])
@require_auth
def quality_history(version_id: str):
    return jsonify(_service().quality_history(version_id))


@voice_city_bp.route("/versions/<version_id>/quality", methods=["POST"])
@require_auth
def record_quality(version_id: str):
    data = _body()
    result = _service().record_quality_evaluation(
        version_id,
        metrics=data.get("metrics") or {},
        duration_tested_s=float(data.get("duration_tested_s", 0.0)),
        notes=data.get("notes"),
    )
    return _commit(result, 201)


@voice_city_bp.route("/audit", methods=["GET"])
@require_auth
def audit_log():
    return jsonify(
        _service().audit_log(
            voice_id=request.args.get("voice_id"),
            limit=int(request.args.get("limit", 200)),
        )
    )


@voice_city_bp.route("/reference-authorizations", methods=["POST"])
@require_auth
def reference_authorization():
    return _commit(_service().create_reference_authorization(_body()), 201)
