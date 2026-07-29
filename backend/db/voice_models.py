"""Voice City durable data model.

The tables in this module deliberately keep generated voice identity, versions,
previews, candidate experiments, pronunciation rules, safety evidence, and
production snapshots separate.  A production job never reads mutable voice
state: it uses a ``VoiceJobSnapshot`` captured when the job is enqueued.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, GUID, new_uuid, utcnow


class VoiceCityVoice(Base):
    __tablename__ = "voice_city_voices"
    __table_args__ = (
        Index("ix_voice_city_voices_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    voice_type: Mapped[str] = mapped_column(String(30), default="synthetic", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), default="edge", nullable=False)
    model_family: Mapped[str] = mapped_column(String(120), default="parametric-catalog-v1", nullable=False)
    # Kept as a GUID without a database FK to avoid a circular create/drop dependency.
    # The service changes it only after the target immutable version has been flushed.
    current_version_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String(30), default="private", nullable=False)
    safety_classification: Mapped[str] = mapped_column(String(40), default="synthetic", nullable=False)
    ownership_record: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    export_restrictions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    default_use_cases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class VoiceCityVoiceVersion(Base):
    __tablename__ = "voice_city_voice_versions"
    __table_args__ = (
        UniqueConstraint("voice_id", "version_number", name="uq_voice_city_voice_version"),
        Index("ix_voice_city_versions_voice_created", "voice_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    voice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    canonical_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    default_style_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    speaker_embedding_key: Mapped[Optional[str]] = mapped_column(Text)
    model_artifact_key: Mapped[Optional[str]] = mapped_column(Text)
    model_revision: Mapped[str] = mapped_column(String(120), default="catalog-v1", nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    consistency_score: Mapped[Optional[float]] = mapped_column(Float)
    supported_languages: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["en-US"], nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityPreset(Base):
    __tablename__ = "voice_city_presets"
    __table_args__ = (
        Index("ix_voice_city_presets_org_category", "organization_id", "category"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_voice_version_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voice_versions.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(80), default="custom", nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VoiceCityCandidateSet(Base):
    __tablename__ = "voice_city_candidate_sets"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityCandidate(Base):
    __tablename__ = "voice_city_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_set_id", "ordinal", name="uq_voice_city_candidate_ordinal"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    candidate_set_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("voice_city_candidate_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    uniqueness_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="candidate", nullable=False)
    source_versions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityPreview(Base):
    __tablename__ = "voice_city_previews"
    __table_args__ = (
        Index("ix_voice_city_previews_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    voice_version_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voice_versions.id", ondelete="SET NULL"), index=True
    )
    candidate_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_candidates.id", ondelete="SET NULL"), index=True
    )
    script_id: Mapped[Optional[str]] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    audio_key: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    voice_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityGenerationJob(Base):
    __tablename__ = "voice_city_generation_jobs"
    __table_args__ = (
        Index("ix_voice_city_generation_claim", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voice_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(120))
    error: Mapped[Optional[str]] = mapped_column(Text)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    locked_by: Mapped[Optional[str]] = mapped_column(String(120))
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VoiceCityPronunciationRule(Base):
    __tablename__ = "voice_city_pronunciation_rules"
    __table_args__ = (
        Index("ix_voice_city_pronunciation_scope", "organization_id", "voice_id", "priority"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voice_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    replacement: Mapped[str] = mapped_column(String(1000), nullable=False)
    language: Mapped[str] = mapped_column(String(30), default="en-US", nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), default="literal", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VoiceCityAutomationTrack(Base):
    __tablename__ = "voice_city_automation_tracks"
    __table_args__ = (
        Index("ix_voice_city_automation_scope", "organization_id", "voice_id", "scope_type", "scope_key"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    scope_type: Mapped[str] = mapped_column(String(30), default="chapter", nullable=False)
    scope_key: Mapped[str] = mapped_column(String(300), nullable=False)
    parameter_path: Mapped[str] = mapped_column(String(200), nullable=False)
    keyframes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    interpolation: Mapped[str] = mapped_column(String(30), default="linear", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VoiceCitySafetyCheck(Base):
    __tablename__ = "voice_city_safety_checks"
    __table_args__ = (
        Index("ix_voice_city_safety_subject", "subject_type", "subject_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[str] = mapped_column(GUID, nullable=False)
    check_type: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityAuditEvent(Base):
    __tablename__ = "voice_city_audit_events"
    __table_args__ = (
        Index("ix_voice_city_audit_org_created", "organization_id", "created_at"),
        Index("ix_voice_city_audit_voice_created", "voice_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    voice_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[Optional[str]] = mapped_column(GUID)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityQualityEvaluation(Base):
    __tablename__ = "voice_city_quality_evaluations"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    voice_version_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("voice_city_voice_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    duration_tested_s: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityReferenceAuthorization(Base):
    """Metadata-only authorization record for the future reference-voice workflow.

    The initial Voice City release does not accept reference audio.  Keeping the
    authorization lifecycle explicit prevents that capability from being added
    later as an ungoverned upload endpoint.
    """

    __tablename__ = "voice_city_reference_authorizations"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    subject_name: Mapped[str] = mapped_column(String(300), nullable=False)
    authorization_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    consent_document_key: Mapped[Optional[str]] = mapped_column(Text)
    talent_agreement_key: Mapped[Optional[str]] = mapped_column(Text)
    identity_verified_by: Mapped[Optional[str]] = mapped_column(GUID)
    identity_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class VoiceCityJobSnapshot(Base):
    """Immutable voice recipe captured for one audiobook production job."""

    __tablename__ = "voice_city_job_snapshots"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_voice_city_job_snapshot_job"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voice_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="SET NULL"), index=True
    )
    voice_version_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voice_versions.id", ondelete="SET NULL"), index=True
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    pronunciation_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    automation_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    direction_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    casting_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(120), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
