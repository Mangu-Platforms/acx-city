"""voice city

Revision ID: c7f4a9b21d63
Revises: 9e8fdbef29e0
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import db.base

revision: str = "c7f4a9b21d63"
down_revision: Union[str, None] = "9e8fdbef29e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def guid():
    return db.base.GUID(length=36)


def upgrade() -> None:
    op.create_table(
        "voice_city_voices",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("voice_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_family", sa.String(length=120), nullable=False),
        sa.Column("current_version_id", guid(), nullable=True),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("safety_classification", sa.String(length=40), nullable=False),
        sa.Column("ownership_record", sa.JSON(), nullable=False),
        sa.Column("export_restrictions", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("default_use_cases", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_voices_organization_id", "voice_city_voices", ["organization_id"])
    op.create_index("ix_voice_city_voices_status", "voice_city_voices", ["status"])
    op.create_index("ix_voice_city_voices_current_version_id", "voice_city_voices", ["current_version_id"])
    op.create_index("ix_voice_city_voices_org_status", "voice_city_voices", ["organization_id", "status"])

    op.create_table(
        "voice_city_voice_versions",
        sa.Column("id", guid(), nullable=False),
        sa.Column("voice_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("canonical_parameters", sa.JSON(), nullable=False),
        sa.Column("default_style_parameters", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("speaker_embedding_key", sa.Text(), nullable=True),
        sa.Column("model_artifact_key", sa.Text(), nullable=True),
        sa.Column("model_revision", sa.String(length=120), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("consistency_score", sa.Float(), nullable=True),
        sa.Column("supported_languages", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_id", "version_number", name="uq_voice_city_voice_version"),
    )
    op.create_index("ix_voice_city_voice_versions_voice_id", "voice_city_voice_versions", ["voice_id"])
    op.create_index("ix_voice_city_voice_versions_fingerprint", "voice_city_voice_versions", ["fingerprint"])
    op.create_index("ix_voice_city_versions_voice_created", "voice_city_voice_versions", ["voice_id", "created_at"])

    op.create_table(
        "voice_city_presets",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=True),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("source_voice_version_id", guid(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("is_template", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_voice_version_id"], ["voice_city_voice_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_presets_organization_id", "voice_city_presets", ["organization_id"])
    op.create_index("ix_voice_city_presets_org_category", "voice_city_presets", ["organization_id", "category"])

    op.create_table(
        "voice_city_candidate_sets",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_candidate_sets_organization_id", "voice_city_candidate_sets", ["organization_id"])

    op.create_table(
        "voice_city_candidates",
        sa.Column("id", guid(), nullable=False),
        sa.Column("candidate_set_id", guid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("canonical_parameters", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("consistency_score", sa.Float(), nullable=False),
        sa.Column("uniqueness_score", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_versions", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_set_id"], ["voice_city_candidate_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_set_id", "ordinal", name="uq_voice_city_candidate_ordinal"),
    )
    op.create_index("ix_voice_city_candidates_candidate_set_id", "voice_city_candidates", ["candidate_set_id"])
    op.create_index("ix_voice_city_candidates_fingerprint", "voice_city_candidates", ["fingerprint"])

    op.create_table(
        "voice_city_previews",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("voice_version_id", guid(), nullable=True),
        sa.Column("candidate_id", guid(), nullable=True),
        sa.Column("script_id", sa.String(length=80), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parameter_overrides", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("audio_key", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("voice_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["voice_city_candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_version_id"], ["voice_city_voice_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_previews_organization_id", "voice_city_previews", ["organization_id"])
    op.create_index("ix_voice_city_previews_voice_version_id", "voice_city_previews", ["voice_version_id"])
    op.create_index("ix_voice_city_previews_candidate_id", "voice_city_previews", ["candidate_id"])
    op.create_index("ix_voice_city_previews_org_created", "voice_city_previews", ["organization_id", "created_at"])

    op.create_table(
        "voice_city_generation_jobs",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("voice_id", guid(), nullable=True),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=120), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_generation_jobs_organization_id", "voice_city_generation_jobs", ["organization_id"])
    op.create_index("ix_voice_city_generation_jobs_voice_id", "voice_city_generation_jobs", ["voice_id"])
    op.create_index("ix_voice_city_generation_jobs_status", "voice_city_generation_jobs", ["status"])
    op.create_index("ix_voice_city_generation_claim", "voice_city_generation_jobs", ["status", "available_at"])

    op.create_table(
        "voice_city_pronunciation_rules",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("voice_id", guid(), nullable=True),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("pattern", sa.String(length=500), nullable=False),
        sa.Column("replacement", sa.String(length=1000), nullable=False),
        sa.Column("language", sa.String(length=30), nullable=False),
        sa.Column("rule_type", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_pronunciation_rules_organization_id", "voice_city_pronunciation_rules", ["organization_id"])
    op.create_index("ix_voice_city_pronunciation_rules_voice_id", "voice_city_pronunciation_rules", ["voice_id"])
    op.create_index("ix_voice_city_pronunciation_scope", "voice_city_pronunciation_rules", ["organization_id", "voice_id", "priority"])

    op.create_table(
        "voice_city_automation_tracks",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("voice_id", guid(), nullable=False),
        sa.Column("project_id", guid(), nullable=True),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("scope_key", sa.String(length=300), nullable=False),
        sa.Column("parameter_path", sa.String(length=200), nullable=False),
        sa.Column("keyframes", sa.JSON(), nullable=False),
        sa.Column("interpolation", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_automation_tracks_organization_id", "voice_city_automation_tracks", ["organization_id"])
    op.create_index("ix_voice_city_automation_tracks_voice_id", "voice_city_automation_tracks", ["voice_id"])
    op.create_index("ix_voice_city_automation_tracks_project_id", "voice_city_automation_tracks", ["project_id"])
    op.create_index("ix_voice_city_automation_scope", "voice_city_automation_tracks", ["organization_id", "voice_id", "scope_type", "scope_key"])

    op.create_table(
        "voice_city_safety_checks",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_id", guid(), nullable=False),
        sa.Column("check_type", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_safety_checks_organization_id", "voice_city_safety_checks", ["organization_id"])
    op.create_index("ix_voice_city_safety_subject", "voice_city_safety_checks", ["subject_type", "subject_id", "created_at"])

    op.create_table(
        "voice_city_audit_events",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("actor_user_id", guid(), nullable=True),
        sa.Column("voice_id", guid(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", guid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_audit_events_organization_id", "voice_city_audit_events", ["organization_id"])
    op.create_index("ix_voice_city_audit_events_voice_id", "voice_city_audit_events", ["voice_id"])
    op.create_index("ix_voice_city_audit_org_created", "voice_city_audit_events", ["organization_id", "created_at"])
    op.create_index("ix_voice_city_audit_voice_created", "voice_city_audit_events", ["voice_id", "created_at"])

    op.create_table(
        "voice_city_quality_evaluations",
        sa.Column("id", guid(), nullable=False),
        sa.Column("voice_version_id", guid(), nullable=False),
        sa.Column("evaluation_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("duration_tested_s", sa.Float(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["voice_version_id"], ["voice_city_voice_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_quality_evaluations_voice_version_id", "voice_city_quality_evaluations", ["voice_version_id"])

    op.create_table(
        "voice_city_reference_authorizations",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("subject_name", sa.String(length=300), nullable=False),
        sa.Column("authorization_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("consent_document_key", sa.Text(), nullable=True),
        sa.Column("talent_agreement_key", sa.Text(), nullable=True),
        sa.Column("identity_verified_by", guid(), nullable=True),
        sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_city_reference_authorizations_organization_id", "voice_city_reference_authorizations", ["organization_id"])

    op.create_table(
        "voice_city_job_snapshots",
        sa.Column("id", guid(), nullable=False),
        sa.Column("job_id", guid(), nullable=False),
        sa.Column("voice_id", guid(), nullable=True),
        sa.Column("voice_version_id", guid(), nullable=True),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("canonical_parameters", sa.JSON(), nullable=False),
        sa.Column("pronunciation_rules", sa.JSON(), nullable=False),
        sa.Column("automation_snapshot", sa.JSON(), nullable=False),
        sa.Column("direction_snapshot", sa.JSON(), nullable=False),
        sa.Column("casting_snapshot", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("model_revision", sa.String(length=120), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["voice_version_id"], ["voice_city_voice_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_voice_city_job_snapshot_job"),
    )
    op.create_index("ix_voice_city_job_snapshots_job_id", "voice_city_job_snapshots", ["job_id"])
    op.create_index("ix_voice_city_job_snapshots_voice_id", "voice_city_job_snapshots", ["voice_id"])
    op.create_index("ix_voice_city_job_snapshots_voice_version_id", "voice_city_job_snapshots", ["voice_version_id"])
    op.create_index("ix_voice_city_job_snapshots_fingerprint", "voice_city_job_snapshots", ["fingerprint"])


def downgrade() -> None:
    for table in [
        "voice_city_job_snapshots",
        "voice_city_reference_authorizations",
        "voice_city_quality_evaluations",
        "voice_city_audit_events",
        "voice_city_safety_checks",
        "voice_city_automation_tracks",
        "voice_city_pronunciation_rules",
        "voice_city_generation_jobs",
        "voice_city_previews",
        "voice_city_candidates",
        "voice_city_candidate_sets",
        "voice_city_presets",
        "voice_city_voice_versions",
        "voice_city_voices",
    ]:
        op.drop_table(table)
