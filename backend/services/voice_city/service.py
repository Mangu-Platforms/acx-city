"""Application service for the complete Voice City lifecycle."""
from __future__ import annotations

import copy
import os
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from db.base import utcnow
from db.models import Project
from db.voice_models import (
    VoiceCityAuditEvent,
    VoiceCityAutomationTrack,
    VoiceCityCandidate,
    VoiceCityCandidateSet,
    VoiceCityGenerationJob,
    VoiceCityJobSnapshot,
    VoiceCityPreset,
    VoiceCityPronunciationRule,
    VoiceCityQualityEvaluation,
    VoiceCityReferenceAuthorization,
    VoiceCitySafetyCheck,
    VoiceCityVoice,
    VoiceCityVoiceVersion,
)
from services.providers import ProviderRegistry
from .generator import (
    CandidateSpec,
    breed_candidate,
    generate_candidates,
    mutate_candidate,
    parameters_from_description,
    score_parameters,
    select_provider_voice,
)
from .parameter_schema import (
    CONTROL_BY_PATH,
    ParameterValidationError,
    artifact_fingerprint,
    canonical_fingerprint,
    merge_parameter_patch,
    normalize_parameters,
    schema_document,
    validate_parameter_paths,
)
from .preset_library import built_in_presets, get_built_in_preset
from .pronunciation_engine import PronunciationRuleError, serialize_rules, validate_rule
from .production import attach_voice_snapshot
from .voice_optimizer import OptimizationError, enqueue_optimization, request_cancel
from .safety_classifier import (
    ProtectedVoiceRegistry,
    screen_export,
    screen_generation_prompt,
    screen_reference_workflow,
)


class VoiceCityError(ValueError):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_version(version: VoiceCityVoiceVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "voice_id": version.voice_id,
        "version_number": version.version_number,
        "schema_version": version.schema_version,
        "parameters": version.canonical_parameters,
        "default_style_parameters": version.default_style_parameters,
        "provider": version.provider,
        "provider_voice_id": version.provider_voice_id,
        "model_revision": version.model_revision,
        "seed": version.seed,
        "quality_score": version.quality_score,
        "consistency_score": version.consistency_score,
        "supported_languages": version.supported_languages,
        "status": version.status,
        "fingerprint": version.fingerprint,
        "provenance": version.provenance,
        "change_note": version.change_note,
        "created_at": _iso(version.created_at),
    }


def serialize_voice(voice: VoiceCityVoice, current_version: VoiceCityVoiceVersion | None = None) -> dict[str, Any]:
    return {
        "id": voice.id,
        "organization_id": voice.organization_id,
        "name": voice.name,
        "description": voice.description,
        "voice_type": voice.voice_type,
        "status": voice.status,
        "provider": voice.provider,
        "model_family": voice.model_family,
        "current_version_id": voice.current_version_id,
        "visibility": voice.visibility,
        "safety_classification": voice.safety_classification,
        "ownership_record": voice.ownership_record,
        "export_restrictions": voice.export_restrictions,
        "tags": voice.tags,
        "default_use_cases": voice.default_use_cases,
        "created_at": _iso(voice.created_at),
        "updated_at": _iso(voice.updated_at),
        "revoked_at": _iso(voice.revoked_at),
        "current_version": serialize_version(current_version) if current_version else None,
    }


def serialize_candidate(candidate: VoiceCityCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "candidate_set_id": candidate.candidate_set_id,
        "ordinal": candidate.ordinal,
        "name": candidate.name,
        "parameters": candidate.canonical_parameters,
        "provider": candidate.provider,
        "provider_voice_id": candidate.provider_voice_id,
        "quality_score": candidate.quality_score,
        "consistency_score": candidate.consistency_score,
        "uniqueness_score": candidate.uniqueness_score,
        "fingerprint": candidate.fingerprint,
        "status": candidate.status,
        "source_versions": candidate.source_versions,
        "warnings": candidate.warnings,
        "created_at": _iso(candidate.created_at),
    }


def serialize_generation_job(job: VoiceCityGenerationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "voice_id": job.voice_id,
        "operation": job.operation,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "request": job.request_payload,
        "result": job.result_payload,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": _iso(job.available_at),
        "cancel_requested": job.cancel_requested,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


class VoiceCityService:
    def __init__(
        self,
        session: Session,
        *,
        organization_id: str,
        user_id: str | None,
        provider_registry: ProviderRegistry | None = None,
        protected_registry: ProtectedVoiceRegistry | None = None,
    ):
        self.session = session
        self.organization_id = organization_id
        self.user_id = user_id
        self.providers = provider_registry or ProviderRegistry()
        self.protected_registry = protected_registry or ProtectedVoiceRegistry.from_env()

    # ------------------------------------------------------------------
    # Shared guards / evidence
    # ------------------------------------------------------------------
    def _audit(
        self,
        event_type: str,
        *,
        subject_type: str,
        subject_id: str | None = None,
        voice_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.session.add(
            VoiceCityAuditEvent(
                organization_id=self.organization_id,
                actor_user_id=self.user_id,
                voice_id=voice_id,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=dict(payload or {}),
            )
        )

    def _safety_check(
        self,
        *,
        subject_type: str,
        subject_id: str,
        check_type: str,
        outcome: str,
        score: float | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.session.add(
            VoiceCitySafetyCheck(
                organization_id=self.organization_id,
                subject_type=subject_type,
                subject_id=subject_id,
                check_type=check_type,
                outcome=outcome,
                score=score,
                details=dict(details or {}),
            )
        )

    def _get_voice(self, voice_id: str, *, include_deleted: bool = False) -> VoiceCityVoice:
        voice = self.session.get(VoiceCityVoice, voice_id)
        if (
            voice is None
            or voice.organization_id != self.organization_id
            or (voice.deleted_at is not None and not include_deleted)
        ):
            raise VoiceCityError("Voice not found")
        return voice

    def _get_version(self, version_id: str) -> tuple[VoiceCityVoice, VoiceCityVoiceVersion]:
        version = self.session.get(VoiceCityVoiceVersion, version_id)
        if version is None:
            raise VoiceCityError("Voice version not found")
        voice = self._get_voice(version.voice_id)
        return voice, version

    def _get_candidate(self, candidate_id: str) -> tuple[VoiceCityCandidateSet, VoiceCityCandidate]:
        candidate = self.session.get(VoiceCityCandidate, candidate_id)
        if candidate is None:
            raise VoiceCityError("Candidate not found")
        candidate_set = self.session.get(VoiceCityCandidateSet, candidate.candidate_set_id)
        if candidate_set is None or candidate_set.organization_id != self.organization_id:
            raise VoiceCityError("Candidate not found")
        return candidate_set, candidate

    def _available_voices(self, provider: str, locale: str | None = None) -> list[dict[str, Any]]:
        adapter = self.providers.get(provider)
        if adapter is None:
            raise VoiceCityError(f"Unknown provider {provider!r}")
        try:
            return adapter.list_voices(locale[:2] if locale else None)
        except Exception:
            return []

    def capabilities(self) -> dict[str, Any]:
        reference_enabled = os.getenv("VOICE_CITY_REFERENCE_VOICES_ENABLED", "false").lower() == "true"
        return {
            "synthetic_voice_creation": True,
            "reference_voice_creation": reference_enabled,
            "voice_cloning": False,
            "anonymous_model_export": False,
            "public_model_export": False,
            "parameter_schema_version": schema_document("simple")["schema_version"],
            "modes": schema_document("simple")["modes"],
            "providers": self.providers.describe_all(),
            "preview_max_characters": int(os.getenv("VOICE_CITY_PREVIEW_MAX_CHARS", "1800")),
            "production_snapshotting": True,
            "pronunciation_dictionary": True,
            "chapter_automation": True,
            "character_casting": True,
            "automatic_dialogue_detection": True,
            "scene_and_sentence_direction": True,
            "provenance_sidecars": True,
            "protected_profile_registry_configured": bool(self.protected_registry.profiles),
            "persistent_identity_optimization": bool(os.getenv("VOICE_CITY_MODEL_SERVER_URL", "").strip()),
            "model_server_protocol": "voice-city-http-v1",
        }

    # ------------------------------------------------------------------
    # Voice / immutable version lifecycle
    # ------------------------------------------------------------------
    def list_voices(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = self.session.query(VoiceCityVoice).filter(
            VoiceCityVoice.organization_id == self.organization_id,
            VoiceCityVoice.deleted_at.is_(None),
        )
        if status:
            query = query.filter(VoiceCityVoice.status == status)
        voices = query.order_by(VoiceCityVoice.updated_at.desc()).all()
        result = []
        for voice in voices:
            version = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
            result.append(serialize_voice(voice, version))
        return result

    def get_voice(self, voice_id: str) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        current = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
        versions = (
            self.session.query(VoiceCityVoiceVersion)
            .filter(VoiceCityVoiceVersion.voice_id == voice.id)
            .order_by(VoiceCityVoiceVersion.version_number.desc())
            .all()
        )
        payload = serialize_voice(voice, current)
        payload["versions"] = [serialize_version(version) for version in versions]
        return payload

    def _create_version(
        self,
        voice: VoiceCityVoice,
        *,
        parameters: Mapping[str, Any],
        provider_voice_id: str,
        change_note: str | None,
        provider: str | None = None,
        status: str = "ready",
        provenance: Mapping[str, Any] | None = None,
    ) -> VoiceCityVoiceVersion:
        canonical, warnings = normalize_parameters(parameters)
        safety = self.protected_registry.check_parameters(canonical)
        if not safety.allowed:
            raise VoiceCityError("Voice profile failed protected-profile similarity screening")
        next_number = (
            self.session.query(func.max(VoiceCityVoiceVersion.version_number))
            .filter(VoiceCityVoiceVersion.voice_id == voice.id)
            .scalar()
            or 0
        ) + 1
        quality, consistency, _uniqueness = score_parameters(canonical)
        effective_provider = provider or voice.provider
        model_revision = "catalog-v1"
        version = VoiceCityVoiceVersion(
            voice_id=voice.id,
            created_by=self.user_id,
            version_number=next_number,
            schema_version=canonical["schema_version"],
            canonical_parameters=canonical,
            default_style_parameters=copy.deepcopy(canonical.get("performance", {})),
            provider=effective_provider,
            provider_voice_id=provider_voice_id,
            model_revision=model_revision,
            seed=int(canonical["seed"]),
            quality_score=quality,
            consistency_score=consistency,
            supported_languages=[str(canonical.get("accent", {}).get("locale", "en-US"))],
            status=status,
            fingerprint=artifact_fingerprint(
                canonical,
                provider=effective_provider,
                provider_voice_id=provider_voice_id,
                model_revision=model_revision,
            ),
            provenance={
                "creation_method": "synthetic-parameter-space",
                "reference_audio": False,
                "schema_warnings": warnings,
                **dict(provenance or {}),
            },
            change_note=change_note,
        )
        self.session.add(version)
        self.session.flush()
        voice.current_version_id = version.id
        voice.provider = version.provider
        voice.status = "ready" if voice.status == "draft" else voice.status
        voice.updated_at = utcnow()
        self._safety_check(
            subject_type="voice_version",
            subject_id=version.id,
            check_type="protected-profile-similarity",
            outcome="passed",
            score=safety.evidence.get("strongest_score"),
            details=safety.as_dict(),
        )
        return version

    def create_voice(
        self,
        *,
        name: str,
        description: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        seed: int = 481928,
        provider: str = "edge",
        provider_voice_id: str | None = None,
        tags: Sequence[str] = (),
        default_use_cases: Sequence[str] = (),
    ) -> dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name or len(clean_name) > 200:
            raise VoiceCityError("Voice name is required and must be 200 characters or fewer")
        decision = screen_generation_prompt(description)
        if not decision.allowed:
            raise VoiceCityError("; ".join(decision.reasons))

        described, prompt_warnings = parameters_from_description(description, seed=seed)
        if parameters:
            canonical, parameter_warnings = merge_parameter_patch(described, parameters, seed=seed)
        else:
            canonical, parameter_warnings = normalize_parameters(described, seed=seed)
        locale = str(canonical.get("accent", {}).get("locale", "en-US"))
        voices = self._available_voices(provider, locale)
        chosen_voice = provider_voice_id or select_provider_voice(
            canonical, provider=provider, available_voices=voices or None
        )

        voice = VoiceCityVoice(
            organization_id=self.organization_id,
            created_by=self.user_id,
            name=clean_name,
            description=(description or "").strip() or None,
            voice_type="synthetic",
            status="draft",
            provider=provider,
            model_family="parametric-catalog-v1",
            visibility="private",
            safety_classification="synthetic-no-reference-audio",
            ownership_record={
                "owner_organization_id": self.organization_id,
                "creator_user_id": self.user_id,
                "source": "synthetic-parameter-space",
                "reference_audio": False,
            },
            export_restrictions={
                "anonymous_export": False,
                "public_model_export": False,
                "provider_terms_apply": True,
            },
            tags=list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip())),
            default_use_cases=list(dict.fromkeys(str(item).strip() for item in default_use_cases if str(item).strip())),
        )
        self.session.add(voice)
        self.session.flush()
        version = self._create_version(
            voice,
            parameters=canonical,
            provider_voice_id=chosen_voice,
            change_note="Initial synthetic voice",
            provenance={
                "description": description,
                "prompt_screen": decision.as_dict(),
                "generation_warnings": prompt_warnings + parameter_warnings,
            },
        )
        self._safety_check(
            subject_type="voice",
            subject_id=voice.id,
            check_type="prompt-impersonation",
            outcome="passed",
            details=decision.as_dict(),
        )
        self._audit(
            "voice.created",
            subject_type="voice",
            subject_id=voice.id,
            voice_id=voice.id,
            payload={"version_id": version.id, "provider": provider, "provider_voice_id": chosen_voice},
        )
        return serialize_voice(voice, version)

    def save_version(
        self,
        voice_id: str,
        *,
        parameters: Mapping[str, Any],
        change_note: str | None = None,
        provider_voice_id: str | None = None,
        expected_current_version_id: str | None = None,
    ) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        if voice.status == "revoked":
            raise VoiceCityError("Revoked voices cannot be versioned")
        if expected_current_version_id and voice.current_version_id != expected_current_version_id:
            raise VoiceCityError("Voice changed since it was loaded; refresh before saving")
        current = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
        chosen_voice = provider_voice_id or (current.provider_voice_id if current else None)
        if not chosen_voice:
            canonical, _ = normalize_parameters(parameters)
            chosen_voice = select_provider_voice(
                canonical,
                provider=voice.provider,
                available_voices=self._available_voices(voice.provider) or None,
            )
        version = self._create_version(
            voice,
            parameters=parameters,
            provider_voice_id=chosen_voice,
            change_note=change_note or "Saved from Voice City",
            provenance={"source_version_id": current.id if current else None},
        )
        self._audit(
            "voice.version_saved",
            subject_type="voice_version",
            subject_id=version.id,
            voice_id=voice.id,
            payload={"version_number": version.version_number, "fingerprint": version.fingerprint},
        )
        return serialize_version(version)

    def rollback(self, voice_id: str, version_id: str) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        _version_voice, version = self._get_version(version_id)
        if version.voice_id != voice.id:
            raise VoiceCityError("Version does not belong to this voice")
        previous = voice.current_version_id
        voice.current_version_id = version.id
        voice.provider = version.provider
        voice.updated_at = utcnow()
        self._audit(
            "voice.rolled_back",
            subject_type="voice_version",
            subject_id=version.id,
            voice_id=voice.id,
            payload={"previous_current_version_id": previous, "new_current_version_id": version.id},
        )
        return serialize_voice(voice, version)

    def update_voice_metadata(
        self,
        voice_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: Sequence[str] | None = None,
        default_use_cases: Sequence[str] | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        if name is not None:
            clean = name.strip()
            if not clean or len(clean) > 200:
                raise VoiceCityError("Voice name must be 1-200 characters")
            voice.name = clean
        if description is not None:
            decision = screen_generation_prompt(description)
            if not decision.allowed:
                raise VoiceCityError("; ".join(decision.reasons))
            voice.description = description.strip() or None
        if tags is not None:
            voice.tags = list(dict.fromkeys(str(item).strip() for item in tags if str(item).strip()))
        if default_use_cases is not None:
            voice.default_use_cases = list(
                dict.fromkeys(str(item).strip() for item in default_use_cases if str(item).strip())
            )
        if visibility is not None:
            if visibility not in {"private", "organization"}:
                raise VoiceCityError("visibility must be private or organization")
            voice.visibility = visibility
        voice.updated_at = utcnow()
        self._audit("voice.metadata_updated", subject_type="voice", subject_id=voice.id, voice_id=voice.id)
        current = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
        return serialize_voice(voice, current)

    def revoke_voice(self, voice_id: str, *, reason: str | None = None) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        voice.status = "revoked"
        voice.revoked_at = utcnow()
        voice.updated_at = utcnow()
        self._audit(
            "voice.revoked",
            subject_type="voice",
            subject_id=voice.id,
            voice_id=voice.id,
            payload={"reason": reason or ""},
        )
        current = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
        return serialize_voice(voice, current)

    def delete_voice(self, voice_id: str) -> None:
        voice = self._get_voice(voice_id)
        voice.deleted_at = utcnow()
        voice.status = "deleted"
        voice.updated_at = utcnow()
        self._audit("voice.deleted", subject_type="voice", subject_id=voice.id, voice_id=voice.id)

    def export_recipe(self, voice_id: str, version_id: str | None = None) -> dict[str, Any]:
        voice = self._get_voice(voice_id)
        version = self.session.get(VoiceCityVoiceVersion, version_id or voice.current_version_id)
        if version is None or version.voice_id != voice.id:
            raise VoiceCityError("Voice version not found")
        decision = screen_export(visibility=voice.visibility, authenticated=bool(self.user_id), voice_status=voice.status)
        if not decision.allowed:
            raise VoiceCityError("; ".join(decision.reasons))
        self._audit(
            "voice.recipe_exported",
            subject_type="voice_version",
            subject_id=version.id,
            voice_id=voice.id,
            payload={"fingerprint": version.fingerprint},
        )
        return {
            "export_version": "1.0",
            "classification": "synthetic-voice-recipe",
            "voice": {"id": voice.id, "name": voice.name, "provider": version.provider},
            "version": serialize_version(version),
            "ownership_record": voice.ownership_record,
            "export_restrictions": voice.export_restrictions,
            "safety": decision.as_dict(),
        }

    # ------------------------------------------------------------------
    # Persistent synthetic identity optimization
    # ------------------------------------------------------------------
    def optimize_version(self, version_id: str) -> dict[str, Any]:
        self._get_version(version_id)
        try:
            job = enqueue_optimization(
                self.session,
                organization_id=self.organization_id,
                user_id=self.user_id,
                voice_version_id=version_id,
            )
        except OptimizationError as exc:
            raise VoiceCityError(str(exc)) from exc
        return serialize_generation_job(job)

    def get_generation_job(self, job_id: str) -> dict[str, Any]:
        job = self.session.get(VoiceCityGenerationJob, job_id)
        if job is None or job.organization_id != self.organization_id:
            raise VoiceCityError("Generation job not found")
        return serialize_generation_job(job)

    def cancel_generation_job(self, job_id: str) -> dict[str, Any]:
        job = self.session.get(VoiceCityGenerationJob, job_id)
        if job is None or job.organization_id != self.organization_id:
            raise VoiceCityError("Generation job not found")
        if job.status in {"succeeded", "failed", "canceled"}:
            return serialize_generation_job(job)
        request_cancel(self.session, job)
        self._audit(
            "generation_job.cancel_requested",
            subject_type="generation_job",
            subject_id=job.id,
            voice_id=job.voice_id,
        )
        return serialize_generation_job(job)

    # ------------------------------------------------------------------
    # Generate, mutate, breed, lock, compare, accept/reject
    # ------------------------------------------------------------------
    def _store_candidates(
        self,
        *,
        operation: str,
        seed: int,
        request_payload: Mapping[str, Any],
        specs: Sequence[CandidateSpec],
        voice_id: str | None = None,
    ) -> dict[str, Any]:
        job = VoiceCityGenerationJob(
            organization_id=self.organization_id,
            voice_id=voice_id,
            created_by=self.user_id,
            operation=operation,
            status="running",
            progress=10,
            stage="validating",
            request_payload=dict(request_payload),
        )
        self.session.add(job)
        candidate_set = VoiceCityCandidateSet(
            organization_id=self.organization_id,
            created_by=self.user_id,
            operation=operation,
            seed=int(seed),
            request_payload=dict(request_payload),
        )
        self.session.add(candidate_set)
        self.session.flush()

        rows: list[VoiceCityCandidate] = []
        for index, spec in enumerate(specs):
            similarity = self.protected_registry.check_parameters(spec.parameters)
            status = "candidate" if similarity.allowed else "blocked"
            row = VoiceCityCandidate(
                candidate_set_id=candidate_set.id,
                ordinal=index,
                name=spec.name,
                canonical_parameters=spec.parameters,
                provider=spec.provider,
                provider_voice_id=spec.provider_voice_id,
                quality_score=spec.quality_score,
                consistency_score=spec.consistency_score,
                uniqueness_score=spec.uniqueness_score,
                fingerprint=spec.fingerprint,
                status=status,
                source_versions=list(spec.source_versions),
                warnings=list(spec.warnings),
            )
            self.session.add(row)
            self.session.flush()
            self._safety_check(
                subject_type="candidate",
                subject_id=row.id,
                check_type="protected-profile-similarity",
                outcome="passed" if similarity.allowed else "blocked",
                score=similarity.evidence.get("strongest_score"),
                details=similarity.as_dict(),
            )
            rows.append(row)

        allowed_rows = [row for row in rows if row.status == "candidate"]
        job.status = "succeeded" if allowed_rows else "failed"
        job.progress = 100
        job.stage = "complete"
        job.result_payload = {
            "candidate_set_id": candidate_set.id,
            "candidate_ids": [row.id for row in rows],
            "allowed_count": len(allowed_rows),
            "blocked_count": len(rows) - len(allowed_rows),
        }
        self._audit(
            f"candidate_set.{operation}",
            subject_type="candidate_set",
            subject_id=candidate_set.id,
            voice_id=voice_id,
            payload=job.result_payload,
        )
        return {
            "generation_job_id": job.id,
            "candidate_set_id": candidate_set.id,
            "operation": operation,
            "candidates": [serialize_candidate(row) for row in rows],
        }

    def generate(
        self,
        *,
        description: str,
        provider: str = "edge",
        count: int = 4,
        seed: int = 481928,
        locked_paths: Sequence[str] = (),
    ) -> dict[str, Any]:
        decision = screen_generation_prompt(description)
        if not decision.allowed:
            raise VoiceCityError("; ".join(decision.reasons))
        validate_parameter_paths(locked_paths)
        specs = generate_candidates(
            description=description,
            provider=provider,
            count=count,
            seed=seed,
            locked_paths=locked_paths,
            available_voices=self._available_voices(provider) or None,
        )
        return self._store_candidates(
            operation="generate",
            seed=seed,
            request_payload={
                "description": description,
                "provider": provider,
                "count": count,
                "locked_paths": list(locked_paths),
                "prompt_screen": decision.as_dict(),
            },
            specs=specs,
        )

    def mutate(
        self,
        version_id: str,
        *,
        request_text: str,
        seed: int | None = None,
        locked_paths: Sequence[str] = (),
    ) -> dict[str, Any]:
        voice, version = self._get_version(version_id)
        decision = screen_generation_prompt(request_text)
        if not decision.allowed:
            raise VoiceCityError("; ".join(decision.reasons))
        spec = mutate_candidate(
            base=version.canonical_parameters,
            request=request_text,
            provider=version.provider,
            available_voices=self._available_voices(version.provider) or None,
            seed=seed,
            locked_paths=locked_paths,
            source_versions=[version.id],
        )
        return self._store_candidates(
            operation="mutate",
            seed=int(spec.parameters["seed"]),
            request_payload={
                "source_version_id": version.id,
                "request": request_text,
                "locked_paths": list(locked_paths),
            },
            specs=[spec],
            voice_id=voice.id,
        )

    def breed(
        self,
        version_a_id: str,
        version_b_id: str,
        *,
        weight_a: float = 0.7,
        seed: int = 481928,
        locked_from_a: Sequence[str] = (),
    ) -> dict[str, Any]:
        voice_a, version_a = self._get_version(version_a_id)
        voice_b, version_b = self._get_version(version_b_id)
        for voice in (voice_a, voice_b):
            licensed_reference = bool(voice.ownership_record.get("licensed_reference"))
            if voice.voice_type != "synthetic" and not licensed_reference:
                raise VoiceCityError("Only synthetic or properly licensed source voices may be blended")
            if voice.status == "revoked":
                raise VoiceCityError("Revoked voices may not be blended")
        provider = version_a.provider
        spec = breed_candidate(
            parent_a=version_a.canonical_parameters,
            parent_b=version_b.canonical_parameters,
            provider=provider,
            weight_a=weight_a,
            seed=seed,
            available_voices=self._available_voices(provider) or None,
            locked_from_a=locked_from_a,
            source_versions=[version_a.id, version_b.id],
        )
        return self._store_candidates(
            operation="breed",
            seed=seed,
            request_payload={
                "version_a_id": version_a.id,
                "version_b_id": version_b.id,
                "weight_a": weight_a,
                "locked_from_a": list(locked_from_a),
            },
            specs=[spec],
        )

    def list_candidates(self, candidate_set_id: str) -> list[dict[str, Any]]:
        candidate_set = self.session.get(VoiceCityCandidateSet, candidate_set_id)
        if candidate_set is None or candidate_set.organization_id != self.organization_id:
            raise VoiceCityError("Candidate set not found")
        rows = (
            self.session.query(VoiceCityCandidate)
            .filter(VoiceCityCandidate.candidate_set_id == candidate_set.id)
            .order_by(VoiceCityCandidate.ordinal.asc())
            .all()
        )
        return [serialize_candidate(row) for row in rows]

    def compare_candidates(self, candidate_ids: Sequence[str]) -> dict[str, Any]:
        if not 2 <= len(candidate_ids) <= 8:
            raise VoiceCityError("Compare between two and eight candidates")
        candidates = [self._get_candidate(candidate_id)[1] for candidate_id in candidate_ids]
        paths = [
            "identity.perceived_age",
            "identity.gender_presentation",
            "identity.vocal_weight",
            "identity.pitch_center",
            "identity.pitch_range",
            "identity.warmth",
            "identity.brightness",
            "identity.texture.breathiness",
            "identity.texture.roughness",
            "performance.speaking_rate",
            "performance.energy",
            "performance.expressiveness",
            "performance.authority",
            "performance.intimacy",
            "accent.strength",
        ]
        from .parameter_schema import get_path

        matrix: list[dict[str, Any]] = []
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                deltas = {
                    path: round(
                        float(get_path(left.canonical_parameters, path, 0.0))
                        - float(get_path(right.canonical_parameters, path, 0.0)),
                        4,
                    )
                    for path in paths
                }
                distance = sum(abs(value) for value in deltas.values()) / len(deltas)
                matrix.append(
                    {
                        "left_id": left.id,
                        "right_id": right.id,
                        "mean_semantic_distance": round(distance, 4),
                        "deltas": deltas,
                    }
                )
        return {"candidates": [serialize_candidate(row) for row in candidates], "pairwise": matrix}

    def accept_candidate(
        self,
        candidate_id: str,
        *,
        voice_id: str | None = None,
        name: str | None = None,
        change_note: str | None = None,
    ) -> dict[str, Any]:
        _candidate_set, candidate = self._get_candidate(candidate_id)
        if candidate.status == "blocked":
            raise VoiceCityError("Blocked candidates cannot be saved")
        if voice_id:
            voice = self._get_voice(voice_id)
            current = self.session.get(VoiceCityVoiceVersion, voice.current_version_id) if voice.current_version_id else None
            if current is not None and current.provider != candidate.provider:
                raise VoiceCityError("Candidate provider does not match the destination voice")
            version = self._create_version(
                voice,
                parameters=candidate.canonical_parameters,
                provider_voice_id=candidate.provider_voice_id,
                change_note=change_note or f"Accepted {candidate.name}",
                provider=candidate.provider,
                provenance={"candidate_id": candidate.id, "source_versions": candidate.source_versions},
            )
        else:
            voice_name = (name or candidate.name).strip()
            voice = VoiceCityVoice(
                organization_id=self.organization_id,
                created_by=self.user_id,
                name=voice_name,
                description="Saved from a Voice City candidate",
                voice_type="synthetic",
                status="draft",
                provider=candidate.provider,
                model_family="parametric-catalog-v1",
                visibility="private",
                safety_classification="synthetic-no-reference-audio",
                ownership_record={
                    "owner_organization_id": self.organization_id,
                    "creator_user_id": self.user_id,
                    "source": "synthetic-candidate",
                    "candidate_id": candidate.id,
                    "reference_audio": False,
                },
                export_restrictions={"anonymous_export": False, "public_model_export": False},
            )
            self.session.add(voice)
            self.session.flush()
            version = self._create_version(
                voice,
                parameters=candidate.canonical_parameters,
                provider_voice_id=candidate.provider_voice_id,
                change_note=change_note or "Initial version from accepted candidate",
                provider=candidate.provider,
                provenance={"candidate_id": candidate.id, "source_versions": candidate.source_versions},
            )
        candidate.status = "accepted"
        self._audit(
            "candidate.accepted",
            subject_type="candidate",
            subject_id=candidate.id,
            voice_id=voice.id,
            payload={"voice_version_id": version.id},
        )
        return serialize_voice(voice, version)

    def reject_candidate(self, candidate_id: str, *, reason: str | None = None) -> dict[str, Any]:
        _candidate_set, candidate = self._get_candidate(candidate_id)
        candidate.status = "rejected"
        self._audit(
            "candidate.rejected",
            subject_type="candidate",
            subject_id=candidate.id,
            payload={"reason": reason or ""},
        )
        return serialize_candidate(candidate)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------
    def list_presets(self) -> list[dict[str, Any]]:
        custom = (
            self.session.query(VoiceCityPreset)
            .filter(VoiceCityPreset.organization_id == self.organization_id)
            .order_by(VoiceCityPreset.updated_at.desc())
            .all()
        )
        return built_in_presets() + [
            {
                "id": preset.id,
                "name": preset.name,
                "description": preset.description,
                "category": preset.category,
                "is_template": preset.is_template,
                "parameters": preset.parameters,
                "source_voice_version_id": preset.source_voice_version_id,
                "created_at": _iso(preset.created_at),
                "updated_at": _iso(preset.updated_at),
            }
            for preset in custom
        ]

    def create_preset(
        self,
        *,
        name: str,
        parameters: Mapping[str, Any],
        description: str | None = None,
        category: str = "custom",
        source_voice_version_id: str | None = None,
    ) -> dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name or len(clean_name) > 200:
            raise VoiceCityError("Preset name is required and must be 200 characters or fewer")
        canonical, warnings = normalize_parameters(parameters)
        if source_voice_version_id:
            self._get_version(source_voice_version_id)
        preset = VoiceCityPreset(
            organization_id=self.organization_id,
            created_by=self.user_id,
            name=clean_name,
            description=(description or "").strip() or None,
            schema_version=canonical["schema_version"],
            parameters=canonical,
            source_voice_version_id=source_voice_version_id,
            category=category.strip() or "custom",
            is_template=False,
        )
        self.session.add(preset)
        self.session.flush()
        self._audit(
            "preset.created",
            subject_type="preset",
            subject_id=preset.id,
            payload={"warnings": warnings},
        )
        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "category": preset.category,
            "is_template": False,
            "parameters": preset.parameters,
            "source_voice_version_id": preset.source_voice_version_id,
        }

    def resolve_preset(self, preset_id: str) -> dict[str, Any]:
        system = get_built_in_preset(preset_id)
        if system:
            return system
        preset = self.session.get(VoiceCityPreset, preset_id)
        if preset is None or preset.organization_id != self.organization_id:
            raise VoiceCityError("Preset not found")
        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "category": preset.category,
            "is_template": preset.is_template,
            "parameters": preset.parameters,
            "source_voice_version_id": preset.source_voice_version_id,
        }

    def delete_preset(self, preset_id: str) -> None:
        if preset_id.startswith("system:"):
            raise VoiceCityError("Built-in templates cannot be deleted")
        preset = self.session.get(VoiceCityPreset, preset_id)
        if preset is None or preset.organization_id != self.organization_id:
            raise VoiceCityError("Preset not found")
        self.session.delete(preset)
        self._audit("preset.deleted", subject_type="preset", subject_id=preset.id)

    # ------------------------------------------------------------------
    # Pronunciation dictionary
    # ------------------------------------------------------------------
    def list_pronunciation_rules(self, *, voice_id: str | None = None) -> list[dict[str, Any]]:
        query = self.session.query(VoiceCityPronunciationRule).filter(
            VoiceCityPronunciationRule.organization_id == self.organization_id
        )
        if voice_id:
            self._get_voice(voice_id)
            query = query.filter(
                or_(
                    VoiceCityPronunciationRule.voice_id.is_(None),
                    VoiceCityPronunciationRule.voice_id == voice_id,
                )
            )
        rows = query.order_by(
            VoiceCityPronunciationRule.priority.desc(), VoiceCityPronunciationRule.pattern.asc()
        ).all()
        return serialize_rules(rows)

    def create_pronunciation_rule(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            rule = validate_rule(payload)
        except PronunciationRuleError as exc:
            raise VoiceCityError(str(exc)) from exc
        voice_id = payload.get("voice_id")
        if voice_id:
            self._get_voice(str(voice_id))
        row = VoiceCityPronunciationRule(
            organization_id=self.organization_id,
            voice_id=str(voice_id) if voice_id else None,
            created_by=self.user_id,
            pattern=rule["pattern"],
            replacement=rule["replacement"],
            language=rule["language"],
            rule_type=rule["rule_type"],
            priority=rule["priority"],
            case_sensitive=rule["case_sensitive"],
            enabled=rule["enabled"],
            notes=str(payload.get("notes") or "") or None,
        )
        self.session.add(row)
        self.session.flush()
        self._audit(
            "pronunciation_rule.created",
            subject_type="pronunciation_rule",
            subject_id=row.id,
            voice_id=row.voice_id,
        )
        return serialize_rules([row])[0]

    def update_pronunciation_rule(self, rule_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        row = self.session.get(VoiceCityPronunciationRule, rule_id)
        if row is None or row.organization_id != self.organization_id:
            raise VoiceCityError("Pronunciation rule not found")
        merged = {
            "id": row.id,
            "pattern": payload.get("pattern", row.pattern),
            "replacement": payload.get("replacement", row.replacement),
            "language": payload.get("language", row.language),
            "rule_type": payload.get("rule_type", row.rule_type),
            "priority": payload.get("priority", row.priority),
            "case_sensitive": payload.get("case_sensitive", row.case_sensitive),
            "enabled": payload.get("enabled", row.enabled),
        }
        try:
            rule = validate_rule(merged)
        except PronunciationRuleError as exc:
            raise VoiceCityError(str(exc)) from exc
        row.pattern = rule["pattern"]
        row.replacement = rule["replacement"]
        row.language = rule["language"]
        row.rule_type = rule["rule_type"]
        row.priority = rule["priority"]
        row.case_sensitive = rule["case_sensitive"]
        row.enabled = rule["enabled"]
        if "notes" in payload:
            row.notes = str(payload.get("notes") or "") or None
        row.updated_at = utcnow()
        self._audit(
            "pronunciation_rule.updated",
            subject_type="pronunciation_rule",
            subject_id=row.id,
            voice_id=row.voice_id,
        )
        return serialize_rules([row])[0]

    def delete_pronunciation_rule(self, rule_id: str) -> None:
        row = self.session.get(VoiceCityPronunciationRule, rule_id)
        if row is None or row.organization_id != self.organization_id:
            raise VoiceCityError("Pronunciation rule not found")
        voice_id = row.voice_id
        self.session.delete(row)
        self._audit(
            "pronunciation_rule.deleted",
            subject_type="pronunciation_rule",
            subject_id=rule_id,
            voice_id=voice_id,
        )

    # ------------------------------------------------------------------
    # Automation curves
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_keyframes(keyframes: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
        normalized: list[dict[str, float]] = []
        if not keyframes:
            raise VoiceCityError("At least one keyframe is required")
        if len(keyframes) > 500:
            raise VoiceCityError("An automation track may contain at most 500 keyframes")
        for frame in keyframes:
            try:
                at = float(frame["at"])
                value = float(frame["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise VoiceCityError("Each keyframe requires numeric at and value fields") from exc
            normalized.append({"at": max(0.0, min(1.0, at)), "value": value})
        normalized.sort(key=lambda item: item["at"])
        return normalized

    @staticmethod
    def _serialize_automation_track(row: VoiceCityAutomationTrack) -> dict[str, Any]:
        return {
            "id": row.id,
            "voice_id": row.voice_id,
            "project_id": row.project_id,
            "scope_type": row.scope_type,
            "scope_key": row.scope_key,
            "parameter_path": row.parameter_path,
            "keyframes": row.keyframes,
            "interpolation": row.interpolation,
            "enabled": row.enabled,
        }

    def _validate_project_scope(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        project = self.session.get(Project, str(project_id))
        if project is None or project.organization_id != self.organization_id:
            raise VoiceCityError("Project not found")
        return project.id

    def list_automation_tracks(self, voice_id: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
        self._get_voice(voice_id)
        query = self.session.query(VoiceCityAutomationTrack).filter(
            VoiceCityAutomationTrack.organization_id == self.organization_id,
            VoiceCityAutomationTrack.voice_id == voice_id,
        )
        if project_id is not None:
            validated_project_id = self._validate_project_scope(project_id)
            query = query.filter(
                or_(
                    VoiceCityAutomationTrack.project_id.is_(None),
                    VoiceCityAutomationTrack.project_id == validated_project_id,
                )
            )
        rows = query.order_by(VoiceCityAutomationTrack.created_at.asc(), VoiceCityAutomationTrack.id.asc()).all()
        return [self._serialize_automation_track(row) for row in rows]

    def create_automation_track(self, voice_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._get_voice(voice_id)
        parameter_path = str(payload.get("parameter_path") or "")
        validate_parameter_paths([parameter_path])
        if CONTROL_BY_PATH[parameter_path].control_type != "slider":
            raise VoiceCityError("Only numeric controls can be automated")
        scope_type = str(payload.get("scope_type") or "chapter")
        if scope_type not in {"global", "chapter", "scene", "sentence", "character"}:
            raise VoiceCityError("Unsupported automation scope_type")
        interpolation = str(payload.get("interpolation") or "linear")
        if interpolation not in {"linear", "step", "smooth"}:
            raise VoiceCityError("interpolation must be linear, step, or smooth")
        scope_key = str(payload.get("scope_key") or "global").strip()
        if not scope_key or len(scope_key) > 300:
            raise VoiceCityError("scope_key is required and must be 300 characters or fewer")
        project_id = self._validate_project_scope(
            str(payload.get("project_id")) if payload.get("project_id") else None
        )
        row = VoiceCityAutomationTrack(
            organization_id=self.organization_id,
            voice_id=voice_id,
            project_id=project_id,
            created_by=self.user_id,
            scope_type=scope_type,
            scope_key=scope_key,
            parameter_path=parameter_path,
            keyframes=self._validate_keyframes(payload.get("keyframes") or []),
            interpolation=interpolation,
            enabled=bool(payload.get("enabled", True)),
        )
        self.session.add(row)
        self.session.flush()
        self._audit(
            "automation_track.created",
            subject_type="automation_track",
            subject_id=row.id,
            voice_id=voice_id,
        )
        return self._serialize_automation_track(row)

    def update_automation_track(self, track_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        row = self.session.get(VoiceCityAutomationTrack, track_id)
        if row is None or row.organization_id != self.organization_id:
            raise VoiceCityError("Automation track not found")
        if "parameter_path" in payload:
            path = str(payload["parameter_path"])
            validate_parameter_paths([path])
            if CONTROL_BY_PATH[path].control_type != "slider":
                raise VoiceCityError("Only numeric controls can be automated")
            row.parameter_path = path
        if "keyframes" in payload:
            row.keyframes = self._validate_keyframes(payload["keyframes"])
        if "interpolation" in payload:
            interpolation = str(payload["interpolation"])
            if interpolation not in {"linear", "step", "smooth"}:
                raise VoiceCityError("interpolation must be linear, step, or smooth")
            row.interpolation = interpolation
        if "scope_type" in payload:
            scope_type = str(payload["scope_type"])
            if scope_type not in {"global", "chapter", "scene", "sentence", "character"}:
                raise VoiceCityError("Unsupported automation scope_type")
            row.scope_type = scope_type
        if "scope_key" in payload:
            scope_key = str(payload["scope_key"]).strip()
            if not scope_key or len(scope_key) > 300:
                raise VoiceCityError("scope_key is required and must be 300 characters or fewer")
            row.scope_key = scope_key
        if "project_id" in payload:
            row.project_id = self._validate_project_scope(
                str(payload.get("project_id")) if payload.get("project_id") else None
            )
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        row.updated_at = utcnow()
        self._audit(
            "automation_track.updated",
            subject_type="automation_track",
            subject_id=row.id,
            voice_id=row.voice_id,
        )
        return self._serialize_automation_track(row)

    def delete_automation_track(self, track_id: str) -> None:
        row = self.session.get(VoiceCityAutomationTrack, track_id)
        if row is None or row.organization_id != self.organization_id:
            raise VoiceCityError("Automation track not found")
        voice_id = row.voice_id
        self.session.delete(row)
        self._audit(
            "automation_track.deleted",
            subject_type="automation_track",
            subject_id=track_id,
            voice_id=voice_id,
        )

    # ------------------------------------------------------------------
    # Production readiness evidence
    # ------------------------------------------------------------------
    @staticmethod
    def readiness_report(metrics: Mapping[str, Any], duration_tested_s: float) -> dict[str, Any]:
        checks = {
            "identity_consistency_30_minutes": float(duration_tested_s) >= 1800.0
            and float(metrics.get("identity_consistency", 0.0)) >= 0.85,
            "pronunciation_accuracy": float(metrics.get("pronunciation_accuracy", 0.0)) >= 0.95,
            "chapter_timbre_stability": float(metrics.get("chapter_timbre_stability", 0.0)) >= 0.85,
            "emotional_controllability": float(metrics.get("emotional_controllability", 0.0)) >= 0.75,
            "no_speaker_drift": int(metrics.get("speaker_drift_events", 999999)) == 0,
            "loudness_consistency": float(metrics.get("max_chapter_loudness_delta_db", 999.0)) <= 1.5,
            "long_form_listening_evaluation": bool(metrics.get("long_form_listening_passed", False)),
            "duplicate_similarity_screening": bool(metrics.get("similarity_screen_passed", False)),
        }
        return {
            "production_ready": all(checks.values()),
            "checks": checks,
            "passed": sum(1 for value in checks.values() if value),
            "required": len(checks),
            "duration_tested_s": float(duration_tested_s),
        }

    def record_quality_evaluation(
        self,
        version_id: str,
        *,
        metrics: Mapping[str, Any],
        duration_tested_s: float,
        notes: str | None = None,
    ) -> dict[str, Any]:
        voice, version = self._get_version(version_id)
        report = self.readiness_report(metrics, duration_tested_s)
        evaluation = VoiceCityQualityEvaluation(
            voice_version_id=version.id,
            evaluation_type="production-readiness",
            status="passed" if report["production_ready"] else "failed",
            duration_tested_s=float(duration_tested_s),
            metrics={**dict(metrics), "readiness": report},
            notes=notes,
        )
        self.session.add(evaluation)
        self.session.flush()
        if report["production_ready"]:
            version.status = "production-ready"
            voice.status = "ready"
        self._audit(
            "quality_evaluation.recorded",
            subject_type="quality_evaluation",
            subject_id=evaluation.id,
            voice_id=voice.id,
            payload=report,
        )
        return {
            "id": evaluation.id,
            "voice_version_id": version.id,
            "status": evaluation.status,
            "metrics": evaluation.metrics,
            "report": report,
            "created_at": _iso(evaluation.created_at),
        }

    def quality_history(self, version_id: str) -> list[dict[str, Any]]:
        self._get_version(version_id)
        rows = (
            self.session.query(VoiceCityQualityEvaluation)
            .filter(VoiceCityQualityEvaluation.voice_version_id == version_id)
            .order_by(VoiceCityQualityEvaluation.created_at.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "evaluation_type": row.evaluation_type,
                "status": row.status,
                "duration_tested_s": row.duration_tested_s,
                "metrics": row.metrics,
                "notes": row.notes,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Future, authorized reference workflow (metadata only, feature-gated)
    # ------------------------------------------------------------------
    def create_reference_authorization(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        enabled = os.getenv("VOICE_CITY_REFERENCE_VOICES_ENABLED", "false").lower() == "true"
        if not enabled:
            raise VoiceCityError("Reference-voice creation is disabled until the synthetic system is mature")
        decision = screen_reference_workflow(
            feature_enabled=enabled,
            authorization_status=str(payload.get("status") or "pending"),
            consent_document_key=str(payload.get("consent_document_key") or "") or None,
            identity_verified=bool(payload.get("identity_verified", False)),
        )
        # `identity_verified` and `status` are currently self-attested by the
        # requester -- no document-verification service is integrated yet
        # (reference cloning ships disabled by design; see the product notes).
        # Enforcing `decision.allowed` here is what prevents an authorization
        # record from ever being created in an "approved" state without a
        # consent document and an identity-verified flag both present, and it
        # must hold the moment this feature flag is ever turned on in
        # production -- previously this decision was computed and attached to
        # the audit payload but never actually checked.
        if not decision.allowed:
            raise VoiceCityError("; ".join(decision.reasons))
        row = VoiceCityReferenceAuthorization(
            organization_id=self.organization_id,
            created_by=self.user_id,
            subject_name=str(payload.get("subject_name") or "").strip(),
            authorization_type=str(payload.get("authorization_type") or "talent-agreement"),
            status=str(payload.get("status") or "pending"),
            consent_document_key=str(payload.get("consent_document_key") or "") or None,
            talent_agreement_key=str(payload.get("talent_agreement_key") or "") or None,
            identity_verified_by=self.user_id if payload.get("identity_verified") else None,
            identity_verified_at=utcnow() if payload.get("identity_verified") else None,
            metadata_json={"safety_decision": decision.as_dict()},
        )
        if not row.subject_name:
            raise VoiceCityError("subject_name is required")
        self.session.add(row)
        self.session.flush()
        self._audit(
            "reference_authorization.created",
            subject_type="reference_authorization",
            subject_id=row.id,
            payload=decision.as_dict(),
        )
        return {
            "id": row.id,
            "subject_name": row.subject_name,
            "status": row.status,
            "authorization_type": row.authorization_type,
            "identity_verified_at": _iso(row.identity_verified_at),
            "safety": decision.as_dict(),
        }

    # ------------------------------------------------------------------
    # Production job binding and audit
    # ------------------------------------------------------------------
    def attach_to_job(
        self,
        job: Any,
        *,
        voice_version_id: str,
        performance_overrides: Mapping[str, Any] | None = None,
        direction_plan: Mapping[str, Any] | None = None,
    ) -> VoiceCityJobSnapshot:
        snapshot = attach_voice_snapshot(
            self.session,
            job=job,
            organization_id=self.organization_id,
            voice_version_id=voice_version_id,
            performance_overrides=performance_overrides,
            direction_plan=direction_plan,
            actor_user_id=self.user_id,
        )
        self._audit(
            "voice.attached_to_job",
            subject_type="job",
            subject_id=job.id,
            voice_id=snapshot.voice_id,
            payload={
                "voice_version_id": snapshot.voice_version_id,
                "snapshot_id": snapshot.id,
                "fingerprint": snapshot.fingerprint,
                "character_cast_count": len(snapshot.casting_snapshot or []),
                "automatic_dialogue_detection": bool(
                    (snapshot.direction_snapshot or {}).get("automatic_dialogue_detection", False)
                ),
            },
        )
        return snapshot

    def audit_log(self, *, voice_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = self.session.query(VoiceCityAuditEvent).filter(
            VoiceCityAuditEvent.organization_id == self.organization_id
        )
        if voice_id:
            self._get_voice(voice_id, include_deleted=True)
            query = query.filter(VoiceCityAuditEvent.voice_id == voice_id)
        rows = query.order_by(VoiceCityAuditEvent.created_at.desc()).limit(max(1, min(500, limit))).all()
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "voice_id": row.voice_id,
                "actor_user_id": row.actor_user_id,
                "payload": row.payload,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]
