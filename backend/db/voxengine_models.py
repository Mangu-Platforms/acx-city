"""VoxEngine pipeline models — Phase 5–10 additions from the Production Bible.

These tables extend the existing Voice City models with the multi-agent
pipeline infrastructure, character voice casting, voice cloning, and
pipeline execution tracing.

Reconciliation note: The bible's ``stock_voices`` concept is already served by
VoiceCityVoice + VoiceCityVoiceVersion. This module adds the tables that don't
exist yet.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, GUID, new_uuid, utcnow


# --------------------------------------------------------------------------- #
# Character Voice Map — per-project character-to-voice casting
# --------------------------------------------------------------------------- #
class CharacterVoiceMap(Base):
    """Maps characters in a project to specific voices with tuning parameters.

    Populated by Agent 2 (Character Attribution) and editable by the user
    via the Character Voice Bible panel.
    """
    __tablename__ = "character_voice_map"
    __table_args__ = (
        UniqueConstraint("project_id", "character_name", name="uq_character_voice_project"),
        Index("ix_character_voice_map_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    character_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # References VoiceCityVoice or stock voice slug
    voice_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("voice_city_voices.id", ondelete="SET NULL"))
    voice_slug: Mapped[Optional[str]] = mapped_column(String(100))  # fallback: edge-tts voice name
    pitch_adjustment: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)
    speed_adjustment: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)
    base_emotion: Mapped[str] = mapped_column(String(50), default="neutral")
    is_narrator: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Confidence score from Agent 2 auto-attribution (0.0–1.0)
    attribution_confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Pronunciation Lexicon — per-project word-level pronunciation overrides
# --------------------------------------------------------------------------- #
class PronunciationLexicon(Base):
    """Per-project pronunciation dictionary for proper nouns and heteronyms.

    Auto-suggested by Agent 3 (Text Normalizer) and editable by the user
    via the Lexicon Editor.
    """
    __tablename__ = "pronunciation_lexicon"
    __table_args__ = (
        UniqueConstraint("project_id", "word", name="uq_lexicon_project_word"),
        Index("ix_pronunciation_lexicon_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    word: Mapped[str] = mapped_column(String(255), nullable=False)
    ipa_phoneme: Mapped[Optional[str]] = mapped_column(String(255))  # /ˈhɛloʊ/
    phonetic_spelling: Mapped[Optional[str]] = mapped_column(String(255))  # HEH-loh
    context_note: Mapped[Optional[str]] = mapped_column(Text)  # "only in dialogue"
    # Source: auto = Agent 3 suggestion, manual = user entry
    source: Mapped[str] = mapped_column(String(20), default="manual")
    # Apply across all projects in org
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Voice Clones — user-uploaded reference audio → latent embedding
# --------------------------------------------------------------------------- #
class VoiceClone(Base):
    """Voice clone created from user-uploaded reference audio.

    Uses Fish Speech S2 (or compatible) to compute a 512-dimensional speaker
    embedding from 10–30 seconds of reference audio.
    """
    __tablename__ = "voice_clones"
    __table_args__ = (
        Index("ix_voice_clones_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_audio_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    latent_s3_key: Mapped[Optional[str]] = mapped_column(String(512))  # .npy embedding
    status: Mapped[str] = mapped_column(String(50), default="processing")  # processing|ready|failed
    reference_duration_seconds: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))
    provider: Mapped[str] = mapped_column(String(50), default="fish_speech")
    # Similarity score against protected voice blocklist (0.0–1.0)
    safety_similarity_score: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# --------------------------------------------------------------------------- #
# Pipeline Traces — per-chapter agent execution audit
# --------------------------------------------------------------------------- #
class PipelineTrace(Base):
    """Execution trace for one chapter through the multi-agent pipeline.

    Each row captures timing, cost, and QA results for all 5 agents
    processing a single chapter.
    """
    __tablename__ = "pipeline_traces"
    __table_args__ = (
        Index("ix_pipeline_traces_job_chapter", "job_id", "chapter_number"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Agent 1: Structure Parser (rule-based, $0)
    agent1_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # Agent 2: Character Attribution
    agent2_ms: Mapped[Optional[int]] = mapped_column(Integer)
    agent2_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    # Agent 3: Text Normalizer
    agent3_ms: Mapped[Optional[int]] = mapped_column(Integer)
    agent3_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    # Agent 4: Prosody Planner
    agent4_ms: Mapped[Optional[int]] = mapped_column(Integer)
    agent4_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    # Agent 5: QA Validator
    agent5_ms: Mapped[Optional[int]] = mapped_column(Integer)
    agent5_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))

    # I/O metrics
    characters_in: Mapped[Optional[int]] = mapped_column(Integer)
    characters_out: Mapped[Optional[int]] = mapped_column(Integer)

    # QA result
    qa_passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    qa_issues: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)  # list of issues
    qa_completeness_score: Mapped[Optional[float]] = mapped_column(Float)

    # Status tracking
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending|running|completed|failed
    current_agent: Mapped[Optional[str]] = mapped_column(String(50))
    error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Stock Voices — curated voice catalog (extends Voice City)
# --------------------------------------------------------------------------- #
class StockVoice(Base):
    """Curated stock voice catalog with metadata for browsing and filtering.

    This is the bible's ``stock_voices`` table. Voice City voices are more
    sophisticated (versioned, parameterized); this table provides the simpler
    catalog browsing experience described in the bible with pre-computed
    metadata fields.
    """
    __tablename__ = "stock_voices"
    __table_args__ = (
        Index("ix_stock_voices_active", "is_active"),
        Index("ix_stock_voices_provider", "provider", "is_active"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)  # male|female|neutral
    accent: Mapped[str] = mapped_column(String(50), nullable=False)  # american|british|australian|...
    age_range: Mapped[Optional[str]] = mapped_column(String(30))  # young_adult|adult|senior
    style_tags: Mapped[list[str]] = mapped_column(JSON, default=list)  # narrative|thriller|romance|...
    description: Mapped[Optional[str]] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # edge|polly|kokoro|fish_speech
    provider_voice_id: Mapped[Optional[str]] = mapped_column(String(255))
    latent_s3_key: Mapped[Optional[str]] = mapped_column(String(512))  # 512-dim speaker embedding
    sample_audio_url: Mapped[Optional[str]] = mapped_column(String(512))
    languages: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["en"])
    emotion_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_cloneable: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(50), default="mangu")  # mangu|user|community
    # NULL = global, non-null = org-scoped
    organization_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # Link to Voice City voice if one exists
    voice_city_voice_id: Mapped[Optional[str]] = mapped_column(
        GUID, ForeignKey("voice_city_voices.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
