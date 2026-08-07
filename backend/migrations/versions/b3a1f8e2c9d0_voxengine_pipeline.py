"""voxengine pipeline — multi-agent pipeline, character casting, voice cloning, stock voices

Revision ID: b3a1f8e2c9d0
Revises: c7f4a9b21d63
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import db.base

revision: str = "b3a1f8e2c9d0"
down_revision: Union[str, None] = "c7f4a9b21d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def guid():
    return db.base.GUID(length=36)


def upgrade() -> None:
    # --- Stock Voices (curated catalog) ---
    op.create_table(
        "stock_voices",
        sa.Column("id", guid(), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("gender", sa.String(20), nullable=False),
        sa.Column("accent", sa.String(50), nullable=False),
        sa.Column("age_range", sa.String(30), nullable=True),
        sa.Column("style_tags", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_voice_id", sa.String(255), nullable=True),
        sa.Column("latent_s3_key", sa.String(512), nullable=True),
        sa.Column("sample_audio_url", sa.String(512), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("emotion_tags", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_cloneable", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("organization_id", guid(), nullable=True),
        sa.Column("voice_city_voice_id", guid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_city_voice_id"], ["voice_city_voices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_stock_voices_active", "stock_voices", ["is_active"])
    op.create_index("ix_stock_voices_provider", "stock_voices", ["provider", "is_active"])

    # --- Character Voice Map (per-project character casting) ---
    op.create_table(
        "character_voice_map",
        sa.Column("id", guid(), nullable=False),
        sa.Column("project_id", guid(), nullable=False),
        sa.Column("character_name", sa.String(255), nullable=False),
        sa.Column("voice_id", guid(), nullable=True),
        sa.Column("voice_slug", sa.String(100), nullable=True),
        sa.Column("pitch_adjustment", sa.Numeric(4, 2), nullable=True),
        sa.Column("speed_adjustment", sa.Numeric(4, 2), nullable=True),
        sa.Column("base_emotion", sa.String(50), nullable=True),
        sa.Column("is_narrator", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("attribution_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "character_name", name="uq_character_voice_project"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voice_city_voices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_character_voice_map_project", "character_voice_map", ["project_id"])

    # --- Pronunciation Lexicon (per-project pronunciation dictionary) ---
    op.create_table(
        "pronunciation_lexicon",
        sa.Column("id", guid(), nullable=False),
        sa.Column("project_id", guid(), nullable=False),
        sa.Column("word", sa.String(255), nullable=False),
        sa.Column("ipa_phoneme", sa.String(255), nullable=True),
        sa.Column("phonetic_spelling", sa.String(255), nullable=True),
        sa.Column("context_note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "word", name="uq_lexicon_project_word"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pronunciation_lexicon_project", "pronunciation_lexicon", ["project_id"])

    # --- Voice Clones (user-uploaded reference audio → embedding) ---
    op.create_table(
        "voice_clones",
        sa.Column("id", guid(), nullable=False),
        sa.Column("organization_id", guid(), nullable=False),
        sa.Column("created_by", guid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("reference_audio_s3_key", sa.String(512), nullable=False),
        sa.Column("latent_s3_key", sa.String(512), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("reference_duration_seconds", sa.Numeric(6, 2), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("safety_similarity_score", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_voice_clones_org_status", "voice_clones", ["organization_id", "status"])

    # --- Pipeline Traces (per-chapter agent execution audit) ---
    op.create_table(
        "pipeline_traces",
        sa.Column("id", guid(), nullable=False),
        sa.Column("job_id", guid(), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("agent1_ms", sa.Integer(), nullable=True),
        sa.Column("agent2_ms", sa.Integer(), nullable=True),
        sa.Column("agent2_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("agent3_ms", sa.Integer(), nullable=True),
        sa.Column("agent3_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("agent4_ms", sa.Integer(), nullable=True),
        sa.Column("agent4_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("agent5_ms", sa.Integer(), nullable=True),
        sa.Column("agent5_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("characters_in", sa.Integer(), nullable=True),
        sa.Column("characters_out", sa.Integer(), nullable=True),
        sa.Column("qa_passed", sa.Boolean(), nullable=True),
        sa.Column("qa_issues", sa.JSON(), nullable=True),
        sa.Column("qa_completeness_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("current_agent", sa.String(50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pipeline_traces_job_chapter", "pipeline_traces", ["job_id", "chapter_number"])


def downgrade() -> None:
    op.drop_table("pipeline_traces")
    op.drop_table("voice_clones")
    op.drop_table("pronunciation_lexicon")
    op.drop_table("character_voice_map")
    op.drop_table("stock_voices")
