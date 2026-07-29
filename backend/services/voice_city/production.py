"""Voice City integration with the durable audiobook production pipeline.

Every production binds an immutable narrator version plus snapshots of its
pronunciation rules, automation, director plan, and any character-cast versions.
No mutable Voice City state is consulted while a worker is rendering the book.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.voice_models import (
    VoiceCityAutomationTrack,
    VoiceCityJobSnapshot,
    VoiceCityPronunciationRule,
    VoiceCityVoice,
    VoiceCityVoiceVersion,
)
from .direction_engine import (
    detect_dialogue_segments,
    normalize_character_name,
    validate_direction_plan,
)
from .parameter_mapper import ProviderRenderPlan, apply_automation, map_parameters
from .parameter_schema import artifact_fingerprint, get_path, merge_parameter_patch
from .pronunciation_engine import (
    apply_pronunciation_rules,
    apply_text_interpretation,
    serialize_rules,
)


class VoiceProductionError(ValueError):
    pass


@dataclass(frozen=True)
class DirectedRenderSegment:
    text: str
    kind: str
    speaker: str | None
    scene_index: int
    sentence_index: int
    provider: str
    provider_voice_id: str
    model_revision: str
    identity_fingerprint: str
    render_plan: ProviderRenderPlan
    applied_pronunciation_rules: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


def resolve_voice_version_for_request(
    session: Session, *, organization_id: str, voice_version_id: str
) -> tuple[str, str]:
    """Resolve authoritative provider mapping before quota/provider checks."""
    version = session.get(VoiceCityVoiceVersion, voice_version_id)
    if version is None:
        raise VoiceProductionError("Voice version not found")
    voice = session.get(VoiceCityVoice, version.voice_id)
    if voice is None or voice.organization_id != organization_id or voice.deleted_at is not None:
        raise VoiceProductionError("Voice version is not owned by this organization")
    if voice.status == "revoked":
        raise VoiceProductionError("This voice has been revoked")
    if version.status not in {"draft", "ready", "production-ready"}:
        raise VoiceProductionError(f"Voice version is not usable (status={version.status})")
    return version.provider, version.provider_voice_id


def _serialize_track(track: VoiceCityAutomationTrack) -> dict[str, Any]:
    return {
        "id": track.id,
        "scope_type": track.scope_type,
        "scope_key": track.scope_key,
        "parameter_path": track.parameter_path,
        "keyframes": track.keyframes,
        "interpolation": track.interpolation,
        "enabled": track.enabled,
    }


def _rules_for_voice(session: Session, organization_id: str, voice_id: str) -> list[dict[str, Any]]:
    rules = (
        session.query(VoiceCityPronunciationRule)
        .filter(
            VoiceCityPronunciationRule.organization_id == organization_id,
            VoiceCityPronunciationRule.enabled.is_(True),
            or_(
                VoiceCityPronunciationRule.voice_id.is_(None),
                VoiceCityPronunciationRule.voice_id == voice_id,
            ),
        )
        .order_by(VoiceCityPronunciationRule.priority.desc(), VoiceCityPronunciationRule.created_at.asc())
        .all()
    )
    return serialize_rules(rules)


def _tracks_for_voice(
    session: Session, organization_id: str, voice_id: str, project_id: str | None
) -> list[dict[str, Any]]:
    rows = (
        session.query(VoiceCityAutomationTrack)
        .filter(
            VoiceCityAutomationTrack.organization_id == organization_id,
            VoiceCityAutomationTrack.voice_id == voice_id,
            VoiceCityAutomationTrack.enabled.is_(True),
        )
        .all()
    )
    return [
        _serialize_track(row)
        for row in rows
        if row.project_id is None or str(row.project_id) == str(project_id or "")
    ]


def _load_owned_version(
    session: Session, *, organization_id: str, version_id: str
) -> tuple[VoiceCityVoice, VoiceCityVoiceVersion]:
    version = session.get(VoiceCityVoiceVersion, version_id)
    if version is None:
        raise VoiceProductionError(f"Cast voice version not found: {version_id}")
    voice = session.get(VoiceCityVoice, version.voice_id)
    if voice is None or voice.organization_id != organization_id or voice.deleted_at is not None:
        raise VoiceProductionError("A cast voice version is not owned by this organization")
    if voice.status == "revoked":
        raise VoiceProductionError(f"Cast voice {voice.name!r} has been revoked")
    if version.status not in {"draft", "ready", "production-ready"}:
        raise VoiceProductionError(f"Cast voice {voice.name!r} is not usable (status={version.status})")
    return voice, version


def _capture_casting(
    session: Session,
    *,
    organization_id: str,
    project_id: str | None,
    direction: Mapping[str, Any],
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    for cast in direction.get("cast") or []:
        voice, version = _load_owned_version(
            session,
            organization_id=organization_id,
            version_id=str(cast["voice_version_id"]),
        )
        captured.append(
            {
                "character_name": cast["character_name"],
                "normalized_name": cast["normalized_name"],
                "aliases": list(cast.get("aliases") or []),
                "style_overrides": copy.deepcopy(cast.get("style_overrides") or {}),
                "voice_id": voice.id,
                "voice_name": voice.name,
                "voice_version_id": version.id,
                "version_number": version.version_number,
                "schema_version": version.schema_version,
                "canonical_parameters": copy.deepcopy(version.canonical_parameters),
                "provider": version.provider,
                "provider_voice_id": version.provider_voice_id,
                "model_revision": version.model_revision,
                "fingerprint": version.fingerprint,
                "pronunciation_rules": _rules_for_voice(session, organization_id, voice.id),
                "automation_snapshot": _tracks_for_voice(
                    session, organization_id, voice.id, project_id
                ),
                "provenance": {
                    "source_version_fingerprint": version.fingerprint,
                    "synthetic_only": True,
                    "reference_audio": False,
                },
            }
        )
    return captured


def _snapshot_fingerprint(
    *,
    narrator_render_fingerprint: str,
    pronunciation_rules: Sequence[Mapping[str, Any]],
    automation_snapshot: Sequence[Mapping[str, Any]],
    direction_snapshot: Mapping[str, Any],
    casting_snapshot: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "narrator_render_fingerprint": narrator_render_fingerprint,
        "pronunciation_rules": list(pronunciation_rules),
        "automation_snapshot": list(automation_snapshot),
        "direction_snapshot": dict(direction_snapshot),
        "casting": [
            {
                "character_name": item.get("character_name"),
                "aliases": item.get("aliases"),
                "voice_version_id": item.get("voice_version_id"),
                "fingerprint": item.get("fingerprint"),
                "style_overrides": item.get("style_overrides"),
                "pronunciation_rules": item.get("pronunciation_rules"),
                "automation_snapshot": item.get("automation_snapshot"),
            }
            for item in casting_snapshot
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def attach_voice_snapshot(
    session: Session,
    *,
    job: Any,
    organization_id: str,
    voice_version_id: str,
    performance_overrides: Mapping[str, Any] | None = None,
    direction_plan: Mapping[str, Any] | None = None,
    actor_user_id: str | None = None,
) -> VoiceCityJobSnapshot:
    voice, version = _load_owned_version(
        session, organization_id=organization_id, version_id=voice_version_id
    )

    parameters = copy.deepcopy(version.canonical_parameters)
    warnings: list[str] = []
    if performance_overrides:
        parameters, warnings = merge_parameter_patch(parameters, performance_overrides)

    project_id = str(getattr(job, "project_id", "") or "") or None
    rules = _rules_for_voice(session, organization_id, voice.id)
    automation_snapshot = _tracks_for_voice(session, organization_id, voice.id, project_id)
    try:
        direction = validate_direction_plan(direction_plan, seed=version.seed)
    except ValueError as exc:
        raise VoiceProductionError(str(exc)) from exc
    casting = _capture_casting(
        session,
        organization_id=organization_id,
        project_id=project_id,
        direction=direction,
    )

    narrator_render_fingerprint = artifact_fingerprint(
        parameters,
        provider=version.provider,
        provider_voice_id=version.provider_voice_id,
        model_revision=version.model_revision,
    )
    fingerprint = _snapshot_fingerprint(
        narrator_render_fingerprint=narrator_render_fingerprint,
        pronunciation_rules=rules,
        automation_snapshot=automation_snapshot,
        direction_snapshot=direction,
        casting_snapshot=casting,
    )
    snapshot = VoiceCityJobSnapshot(
        job_id=job.id,
        voice_id=voice.id,
        voice_version_id=version.id,
        schema_version=version.schema_version,
        canonical_parameters=parameters,
        pronunciation_rules=rules,
        automation_snapshot=automation_snapshot,
        direction_snapshot=direction,
        casting_snapshot=casting,
        provider=version.provider,
        provider_voice_id=version.provider_voice_id,
        model_revision=version.model_revision,
        fingerprint=fingerprint,
        provenance={
            "voice_name": voice.name,
            "version_number": version.version_number,
            "source_version_fingerprint": version.fingerprint,
            "narrator_render_fingerprint": narrator_render_fingerprint,
            "performance_override_warnings": warnings,
            "captured_by": actor_user_id,
            "immutable_job_snapshot": True,
            "character_cast_count": len(casting),
            "automatic_dialogue_detection": direction["automatic_dialogue_detection"],
            "synthetic_only": True,
            "reference_audio": False,
        },
    )
    session.add(snapshot)
    # Keep existing job/pipeline fields compatible with catalog providers.
    job.provider = version.provider
    job.voice_id = version.provider_voice_id
    return snapshot


def load_voice_snapshot(session: Session, job_id: str) -> VoiceCityJobSnapshot | None:
    return (
        session.query(VoiceCityJobSnapshot)
        .filter(VoiceCityJobSnapshot.job_id == job_id)
        .one_or_none()
    )


def _style_for_key(styles: Mapping[str, Any], *keys: Any) -> Mapping[str, Any]:
    for key in keys:
        if str(key) in styles:
            return styles[str(key)]
    return {}


def _cast_index(casting: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for cast in casting:
        names = [cast.get("character_name"), *(cast.get("aliases") or [])]
        for name in names:
            normalized = normalize_character_name(str(name or ""))
            if normalized:
                result[normalized] = cast
    return result


def _apply_patch(parameters: Mapping[str, Any], patch: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    if not patch:
        return copy.deepcopy(dict(parameters)), []
    return merge_parameter_patch(parameters, patch)


def prepare_directed_segments(
    snapshot: VoiceCityJobSnapshot,
    text: str,
    *,
    engine: str,
    chapter_index: int,
    chapter_title: str,
) -> list[DirectedRenderSegment]:
    """Resolve dialogue, cast identity, directions, automation, and pronunciation."""
    direction = dict(snapshot.direction_snapshot or {})
    automatic = bool(direction.get("enabled", True) and direction.get("automatic_dialogue_detection", True))
    detected = detect_dialogue_segments(text) if automatic else []
    if not detected:
        detected = [{
            "index": 0,
            "sentence_index": 0,
            "scene_index": 0,
            "kind": "narration",
            "speaker": None,
            "text": text,
            "confidence": 1.0,
            "evidence": "single-narrator",
        }]
    cast_index = _cast_index(snapshot.casting_snapshot or [])
    total = max(len(detected), 1)
    prepared: list[DirectedRenderSegment] = []

    for ordinal, segment in enumerate(detected):
        kind = str(segment.get("kind") or "narration")
        speaker = str(segment.get("speaker") or "").strip() or None
        cast = cast_index.get(normalize_character_name(speaker or "")) if kind == "dialogue" else None
        if kind == "dialogue" and cast is None and direction.get("unknown_dialogue_policy") == "skip":
            continue

        if cast is None:
            identity = {
                "canonical_parameters": snapshot.canonical_parameters,
                "provider": snapshot.provider,
                "provider_voice_id": snapshot.provider_voice_id,
                "model_revision": snapshot.model_revision,
                "fingerprint": (snapshot.provenance or {}).get("narrator_render_fingerprint") or snapshot.fingerprint,
                "pronunciation_rules": snapshot.pronunciation_rules,
                "automation_snapshot": snapshot.automation_snapshot,
                "voice_version_id": snapshot.voice_version_id,
                "voice_name": (snapshot.provenance or {}).get("voice_name"),
                "style_overrides": {},
            }
        else:
            identity = cast

        parameters = copy.deepcopy(identity["canonical_parameters"])
        warnings: list[str] = []
        for patch in (
            direction.get("director_parameter_patch") or {},
            direction.get("default_dialogue_overrides") if kind == "dialogue" else {},
            _style_for_key(
                direction.get("chapter_styles") or {},
                chapter_index,
                chapter_index + 1,
                chapter_title,
            ),
            _style_for_key(
                direction.get("scene_styles") or {},
                f"{chapter_index}:{segment.get('scene_index', 0)}",
                segment.get("scene_index", 0),
            ),
            identity.get("style_overrides") or {},
        ):
            parameters, patch_warnings = _apply_patch(parameters, patch)
            warnings.extend(patch_warnings)

        position = 0.0 if total <= 1 else ordinal / (total - 1)
        tracks = list(snapshot.automation_snapshot or [])
        if cast is not None:
            tracks.extend(identity.get("automation_snapshot") or [])
        automation_scopes = [
            ("chapter", str(chapter_index), True),
            ("chapter", str(chapter_index + 1), False),
            ("chapter", chapter_title, False),
            ("scene", str(segment.get("scene_index", 0)), False),
            ("scene", f"{chapter_index}:{segment.get('scene_index', 0)}", False),
            ("sentence", str(segment.get("sentence_index", ordinal)), False),
        ]
        if speaker:
            automation_scopes.extend([
                ("character", speaker, False),
                ("character", normalize_character_name(speaker), False),
            ])
        for scope_type, scope_key, include_global in automation_scopes:
            parameters, automation_warnings = apply_automation(
                parameters,
                tracks,
                scope_type=scope_type,
                scope_key=scope_key,
                position=position,
                include_global=include_global,
            )
            warnings.extend(automation_warnings)

        rendered_text = apply_text_interpretation(str(segment.get("text") or ""), parameters)
        strength = float(get_path(parameters, "interpretation.pronunciation_rule_strength", 1.0))
        rendered_text, applied_rules = apply_pronunciation_rules(
            rendered_text,
            identity.get("pronunciation_rules") or snapshot.pronunciation_rules,
            strength=strength,
        )
        if not rendered_text.strip():
            continue
        plan = map_parameters(
            parameters,
            provider=str(identity["provider"]),
            provider_voice_id=str(identity["provider_voice_id"]),
            engine=engine,
        )
        identity_fingerprint = artifact_fingerprint(
            parameters,
            provider=str(identity["provider"]),
            provider_voice_id=str(identity["provider_voice_id"]),
            model_revision=str(identity.get("model_revision") or "catalog-v1"),
        )
        current = DirectedRenderSegment(
            text=rendered_text,
            kind=kind,
            speaker=speaker,
            scene_index=int(segment.get("scene_index", 0)),
            sentence_index=int(segment.get("sentence_index", ordinal)),
            provider=str(identity["provider"]),
            provider_voice_id=str(identity["provider_voice_id"]),
            model_revision=str(identity.get("model_revision") or "catalog-v1"),
            identity_fingerprint=identity_fingerprint,
            render_plan=plan,
            applied_pronunciation_rules=tuple(applied_rules),
            metadata={
                "source_segment_index": int(segment.get("index", ordinal)),
                "speaker_confidence": float(segment.get("confidence", 0.0)),
                "speaker_evidence": segment.get("evidence"),
                "voice_version_id": identity.get("voice_version_id"),
                "voice_name": identity.get("voice_name"),
                "direction_warnings": sorted(set(warnings)),
                "cast_applied": cast is not None,
            },
        )
        # Coalesce adjacent segments only when the full render identity and plan
        # are identical. This reduces provider calls without crossing cast turns.
        if (
            prepared
            and prepared[-1].provider == current.provider
            and prepared[-1].provider_voice_id == current.provider_voice_id
            and prepared[-1].render_plan.cache_discriminator() == current.render_plan.cache_discriminator()
            and prepared[-1].kind == current.kind
            and prepared[-1].speaker == current.speaker
            and len(prepared[-1].text) + len(current.text) <= 4500
        ):
            previous = prepared.pop()
            prepared.append(
                DirectedRenderSegment(
                    text=previous.text + current.text,
                    kind=current.kind,
                    speaker=current.speaker,
                    scene_index=current.scene_index,
                    sentence_index=previous.sentence_index,
                    provider=current.provider,
                    provider_voice_id=current.provider_voice_id,
                    model_revision=current.model_revision,
                    identity_fingerprint=current.identity_fingerprint,
                    render_plan=current.render_plan,
                    applied_pronunciation_rules=previous.applied_pronunciation_rules + current.applied_pronunciation_rules,
                    metadata={
                        **current.metadata,
                        "source_segment_indices": [
                            *(previous.metadata.get("source_segment_indices") or [previous.metadata.get("source_segment_index")]),
                            current.metadata.get("source_segment_index"),
                        ],
                    },
                )
            )
        else:
            prepared.append(current)
    return prepared


def prepare_chunk(
    snapshot: VoiceCityJobSnapshot,
    text: str,
    *,
    engine: str,
    chapter_index: int,
    chapter_title: str,
    chunk_index: int,
    chunks_count: int,
) -> tuple[str, ProviderRenderPlan, list[dict[str, Any]], dict[str, Any]]:
    """Backward-compatible single-narrator chunk preparation."""
    position = 0.0 if chunks_count <= 1 else chunk_index / max(chunks_count - 1, 1)
    parameters, automation_warnings = apply_automation(
        snapshot.canonical_parameters,
        snapshot.automation_snapshot,
        scope_type="chapter",
        scope_key=str(chapter_index),
        position=position,
    )
    parameters, title_warnings = apply_automation(
        parameters,
        snapshot.automation_snapshot,
        scope_type="chapter",
        scope_key=chapter_title,
        position=position,
        include_global=False,
    )
    rendered_text = apply_text_interpretation(text, parameters)
    strength = float(get_path(parameters, "interpretation.pronunciation_rule_strength", 1.0))
    rendered_text, applied_rules = apply_pronunciation_rules(
        rendered_text, snapshot.pronunciation_rules, strength=strength
    )
    plan = map_parameters(
        parameters,
        provider=snapshot.provider,
        provider_voice_id=snapshot.provider_voice_id,
        engine=engine,
    )
    metadata = {
        "chapter_index": chapter_index,
        "chapter_title": chapter_title,
        "chunk_index": chunk_index,
        "chunks_count": chunks_count,
        "automation_warnings": automation_warnings + title_warnings,
        "applied_rule_count": sum(item["replacements"] for item in applied_rules),
    }
    return rendered_text, plan, applied_rules, metadata


def production_manifest(snapshot: VoiceCityJobSnapshot, *, job_id: str) -> dict[str, Any]:
    return {
        "manifest_version": "1.1",
        "classification": "synthetic-generated-audio",
        "job_id": job_id,
        "voice_id": snapshot.voice_id,
        "voice_version_id": snapshot.voice_version_id,
        "schema_version": snapshot.schema_version,
        "render_configuration_fingerprint": snapshot.fingerprint,
        "provider": snapshot.provider,
        "provider_voice_id": snapshot.provider_voice_id,
        "model_revision": snapshot.model_revision,
        "pronunciation_rule_count": len(snapshot.pronunciation_rules),
        "automation_track_count": len(snapshot.automation_snapshot),
        "character_cast": [
            {
                "character_name": item.get("character_name"),
                "aliases": item.get("aliases"),
                "voice_id": item.get("voice_id"),
                "voice_version_id": item.get("voice_version_id"),
                "version_number": item.get("version_number"),
                "provider": item.get("provider"),
                "provider_voice_id": item.get("provider_voice_id"),
                "model_revision": item.get("model_revision"),
                "fingerprint": item.get("fingerprint"),
            }
            for item in (snapshot.casting_snapshot or [])
        ],
        "direction": snapshot.direction_snapshot,
        "provenance": snapshot.provenance,
    }
