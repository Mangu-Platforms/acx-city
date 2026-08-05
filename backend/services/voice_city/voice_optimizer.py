"""Durable optimization jobs for persistent synthetic Voice City identities.

This queue uses the same PostgreSQL database and SKIP LOCKED strategy as the
existing audiobook worker.  It does not introduce Redis, Celery, or a second
queueing service.  Jobs are idempotent at the model-server boundary through a
stable job/version key and create a new immutable voice version on success.
"""
from __future__ import annotations

import copy
import logging
import os
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.base import utcnow
from db.voice_models import (
    VoiceCityAuditEvent,
    VoiceCityGenerationJob,
    VoiceCitySafetyCheck,
    VoiceCityVoice,
    VoiceCityVoiceVersion,
)
from .embedding_store import EmbeddingStore
from .generative_provider import (
    GenerativeVoiceProvider,
    RemoteGenerativeVoiceProvider,
)
from .parameter_schema import artifact_fingerprint

log = logging.getLogger("audiobook.voice_city.optimizer")

LEASE_SECONDS = int(os.getenv("VOICE_CITY_OPTIMIZER_LEASE_SECONDS", "1800"))
RETRY_BASE_SECONDS = int(os.getenv("VOICE_CITY_OPTIMIZER_RETRY_SECONDS", "60"))


class OptimizationCanceled(RuntimeError):
    pass


class OptimizationError(RuntimeError):
    pass


def _dialect(session: Session) -> str:
    return session.get_bind().dialect.name


def enqueue_optimization(
    session: Session,
    *,
    organization_id: str,
    user_id: str | None,
    voice_version_id: str,
) -> VoiceCityGenerationJob:
    provider = RemoteGenerativeVoiceProvider()
    if not provider.is_available():
        raise OptimizationError(
            "Persistent identity optimization requires VOICE_CITY_MODEL_SERVER_URL"
        )
    source_version = session.get(VoiceCityVoiceVersion, voice_version_id)
    if source_version is None:
        raise OptimizationError("Voice version not found")
    voice = session.get(VoiceCityVoice, source_version.voice_id)
    if voice is None or voice.organization_id != organization_id or voice.deleted_at is not None:
        raise OptimizationError("Voice version is not owned by this organization")
    if voice.status == "revoked":
        raise OptimizationError("Revoked voices cannot be optimized")

    existing = (
        session.query(VoiceCityGenerationJob)
        .filter(
            VoiceCityGenerationJob.organization_id == organization_id,
            VoiceCityGenerationJob.voice_id == voice.id,
            VoiceCityGenerationJob.operation == "optimize-persistent-identity",
            VoiceCityGenerationJob.status.in_(["queued", "running"]),
        )
        .order_by(VoiceCityGenerationJob.created_at.desc())
        .all()
    )
    for job in existing:
        if str((job.request_payload or {}).get("source_voice_version_id")) == source_version.id:
            return job

    job = VoiceCityGenerationJob(
        organization_id=organization_id,
        voice_id=voice.id,
        created_by=user_id,
        operation="optimize-persistent-identity",
        status="queued",
        progress=0,
        stage="queued",
        request_payload={
            "source_voice_version_id": source_version.id,
            "source_fingerprint": source_version.fingerprint,
            "reference_audio": False,
        },
        result_payload={},
        available_at=utcnow(),
        max_attempts=3,
    )
    session.add(job)
    session.flush()
    session.add(
        VoiceCityAuditEvent(
            organization_id=organization_id,
            actor_user_id=user_id,
            voice_id=voice.id,
            event_type="voice.optimization_queued",
            subject_type="generation_job",
            subject_id=job.id,
            payload={"source_voice_version_id": source_version.id},
        )
    )
    return job


def claim_next_job(session: Session, worker_id: str) -> VoiceCityGenerationJob | None:
    now = utcnow()
    base = (
        select(VoiceCityGenerationJob)
        .where(
            VoiceCityGenerationJob.operation == "optimize-persistent-identity",
            VoiceCityGenerationJob.status == "queued",
            VoiceCityGenerationJob.available_at <= now,
            VoiceCityGenerationJob.cancel_requested.is_(False),
        )
        .order_by(VoiceCityGenerationJob.available_at.asc(), VoiceCityGenerationJob.created_at.asc())
        .limit(1)
    )
    stmt = base.with_for_update(skip_locked=True) if _dialect(session) == "postgresql" else base
    job = session.execute(stmt).scalars().first()
    if job is None:
        return None
    job.status = "running"
    job.stage = "claimed"
    job.locked_by = worker_id
    job.locked_at = now
    job.attempts += 1
    job.updated_at = now
    session.flush()
    return job


def heartbeat(session: Session, job: VoiceCityGenerationJob | None, worker_id: str) -> bool:
    if job is None:
        return False
    session.refresh(job)
    if job.cancel_requested:
        return False
    if job.status != "running" or job.locked_by != worker_id:
        return False
    job.locked_at = utcnow()
    session.flush()
    return True


def request_cancel(session: Session, job: VoiceCityGenerationJob | None) -> None:
    if job is None:
        raise OptimizationError("Optimization job not found")
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "canceled"
        job.stage = "canceled"
        job.locked_by = None
        job.locked_at = None
    job.updated_at = utcnow()
    session.flush()


def _load_source(session: Session, job: VoiceCityGenerationJob) -> tuple[VoiceCityVoice, VoiceCityVoiceVersion]:
    source_id = str((job.request_payload or {}).get("source_voice_version_id") or "")
    version = session.get(VoiceCityVoiceVersion, source_id)
    if version is None:
        raise OptimizationError("Source voice version no longer exists")
    voice = session.get(VoiceCityVoice, version.voice_id)
    if voice is None or voice.organization_id != job.organization_id or voice.deleted_at is not None:
        raise OptimizationError("Source voice is unavailable")
    if voice.status == "revoked":
        raise OptimizationError("Source voice has been revoked")
    if version.fingerprint != (job.request_payload or {}).get("source_fingerprint"):
        raise OptimizationError("Source version fingerprint does not match the queued job")
    return voice, version


def run_optimization_job(
    session: Session,
    job: VoiceCityGenerationJob | None,
    *,
    worker_id: str,
    provider: GenerativeVoiceProvider | None = None,
    embedding_store: EmbeddingStore | None = None,
) -> VoiceCityVoiceVersion:
    if job is None:
        raise OptimizationError("Optimization job not found")
    if job.status != "running" or job.locked_by != worker_id:
        raise OptimizationError("Optimization job is not owned by this worker")
    if job.cancel_requested:
        raise OptimizationCanceled()
    voice, source = _load_source(session, job)
    provider = provider or RemoteGenerativeVoiceProvider()
    if not provider.is_available():
        raise OptimizationError("Voice City model server is not configured")

    job.stage = "materializing-speaker-identity"
    job.progress = 20
    session.flush()
    artifact = provider.create_voice(
        identity_parameters=copy.deepcopy(source.canonical_parameters.get("identity", {})),
        style_parameters={
            "performance": copy.deepcopy(source.canonical_parameters.get("performance", {})),
            "accent": copy.deepcopy(source.canonical_parameters.get("accent", {})),
            "emotion": copy.deepcopy(source.canonical_parameters.get("emotion", {})),
            "narration": copy.deepcopy(source.canonical_parameters.get("narration", {})),
        },
        seed=source.seed,
        metadata={
            "idempotency_key": f"voice-city:{job.id}:{source.fingerprint}",
            "organization_id": job.organization_id,
            "voice_id": voice.id,
            "source_voice_version_id": source.id,
            "synthetic_only": True,
            "reference_audio": False,
        },
    )
    if job.cancel_requested:
        raise OptimizationCanceled()
    similarity = artifact.metadata.get("similarity_screen") if isinstance(artifact.metadata, dict) else None
    if isinstance(similarity, dict) and similarity.get("allowed") is False:
        session.add(
            VoiceCitySafetyCheck(
                organization_id=job.organization_id,
                subject_type="generation_job",
                subject_id=job.id,
                check_type="protected-profile-similarity",
                outcome="blocked",
                score=similarity.get("score"),
                details=similarity,
            )
        )
        raise OptimizationError("Generated identity failed protected-profile similarity screening")

    job.stage = "persisting-artifacts"
    job.progress = 65
    session.flush()

    # Lock the voice while allocating the next immutable version number.
    if _dialect(session) == "postgresql":
        voice = session.execute(
            select(VoiceCityVoice).where(VoiceCityVoice.id == voice.id).with_for_update()
        ).scalar_one()
    next_number = (
        session.query(func.max(VoiceCityVoiceVersion.version_number))
        .filter(VoiceCityVoiceVersion.voice_id == voice.id)
        .scalar()
        or 0
    ) + 1
    optimized = VoiceCityVoiceVersion(
        voice_id=voice.id,
        created_by=job.created_by,
        version_number=next_number,
        schema_version=source.schema_version,
        canonical_parameters=copy.deepcopy(source.canonical_parameters),
        default_style_parameters=copy.deepcopy(source.default_style_parameters),
        provider=artifact.provider,
        provider_voice_id=artifact.provider_voice_id,
        model_revision=artifact.model_revision,
        seed=source.seed,
        quality_score=artifact.quality_score if artifact.quality_score is not None else source.quality_score,
        consistency_score=(
            artifact.consistency_score if artifact.consistency_score is not None else source.consistency_score
        ),
        supported_languages=artifact.supported_languages or source.supported_languages,
        status="ready",
        fingerprint=artifact_fingerprint(
            source.canonical_parameters,
            provider=artifact.provider,
            provider_voice_id=artifact.provider_voice_id,
            model_revision=artifact.model_revision,
        ),
        provenance={
            **dict(source.provenance or {}),
            "creation_method": "persistent-synthetic-identity-optimization",
            "source_voice_version_id": source.id,
            "model_artifact_id": artifact.artifact_id,
            "model_metadata": artifact.metadata,
            "reference_audio": False,
            "optimization_job_id": job.id,
        },
        change_note=f"Persistent synthetic identity optimized from V{source.version_number}",
    )
    session.add(optimized)
    session.flush()
    keys = (embedding_store or EmbeddingStore()).persist(
        organization_id=job.organization_id,
        voice_id=voice.id,
        version_id=optimized.id,
        artifact=artifact,
    )
    optimized.speaker_embedding_key = keys.speaker_embedding_key
    optimized.model_artifact_key = keys.model_artifact_key

    voice.current_version_id = optimized.id
    voice.provider = optimized.provider
    voice.model_family = artifact.model_family
    voice.status = "ready"
    voice.updated_at = utcnow()

    session.add(
        VoiceCitySafetyCheck(
            organization_id=job.organization_id,
            subject_type="voice_version",
            subject_id=optimized.id,
            check_type="protected-profile-similarity",
            outcome="passed",
            score=similarity.get("score") if isinstance(similarity, dict) else None,
            details=similarity or {"provider_evidence": "not supplied", "synthetic_only": True},
        )
    )
    session.add(
        VoiceCityAuditEvent(
            organization_id=job.organization_id,
            actor_user_id=job.created_by,
            voice_id=voice.id,
            event_type="voice.optimization_completed",
            subject_type="voice_version",
            subject_id=optimized.id,
            payload={
                "source_voice_version_id": source.id,
                "generation_job_id": job.id,
                "model_revision": artifact.model_revision,
            },
        )
    )
    job.status = "succeeded"
    job.progress = 100
    job.stage = "complete"
    job.error = None
    job.result_payload = {
        "source_voice_version_id": source.id,
        "voice_version_id": optimized.id,
        "version_number": optimized.version_number,
        "provider": optimized.provider,
        "provider_voice_id": optimized.provider_voice_id,
        "model_revision": optimized.model_revision,
        "speaker_embedding_key": optimized.speaker_embedding_key,
        "model_artifact_key": optimized.model_artifact_key,
        "manifest_key": keys.manifest_key,
    }
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    session.flush()
    return optimized


def mark_canceled(session: Session, job: VoiceCityGenerationJob | None, worker_id: str) -> None:
    if job is None:
        return
    job.status = "canceled"
    job.stage = "canceled"
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    session.flush()


def fail_job(session: Session, job: VoiceCityGenerationJob | None, worker_id: str, error: str) -> None:
    if job is None:
        log.error("could not record optimization failure because job row disappeared: %s", error)
        return
    job.error = error[:4000]
    job.locked_by = None
    job.locked_at = None
    job.updated_at = utcnow()
    if job.cancel_requested:
        job.status = "canceled"
        job.stage = "canceled"
    elif job.attempts < job.max_attempts:
        job.status = "queued"
        job.stage = "retry-wait"
        job.available_at = utcnow() + timedelta(seconds=RETRY_BASE_SECONDS * (2 ** max(0, job.attempts - 1)))
    else:
        job.status = "failed"
        job.stage = "failed"
    session.flush()


def recover_orphans(session: Session, lease_seconds: int = LEASE_SECONDS) -> int:
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    rows = (
        session.query(VoiceCityGenerationJob)
        .filter(
            VoiceCityGenerationJob.operation == "optimize-persistent-identity",
            VoiceCityGenerationJob.status == "running",
            VoiceCityGenerationJob.locked_at.is_not(None),
            VoiceCityGenerationJob.locked_at < cutoff,
        )
        .all()
    )
    for job in rows:
        job.locked_by = None
        job.locked_at = None
        job.updated_at = utcnow()
        if job.cancel_requested:
            job.status = "canceled"
            job.stage = "canceled"
        elif job.attempts >= job.max_attempts:
            job.status = "failed"
            job.stage = "failed"
            job.error = "optimizer worker died and max attempts were exhausted"
        else:
            job.status = "queued"
            job.stage = "recovered"
            job.available_at = utcnow()
    if rows:
        session.flush()
        log.warning("recovered %d orphaned Voice City optimization job(s)", len(rows))
    return len(rows)
