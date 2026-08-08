"""ORM models — the durable system-of-record.

Ownership chain: Organization 1—* Membership *—1 User, and every Project/Job
belongs to an Organization. Access is authorized by walking this chain, never by
possession of a task id (blueprint: "task id no longer authorizes access").
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, GUID, new_uuid, utcnow


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class JobStatus(str, enum.Enum):
    """Job lifecycle. `queued` rows are what the worker claims.

    queued -> running -> (succeeded | needs_review | failed)
              running -> queued        (retry after a recoverable failure)
    queued/running -> canceled         (user cancel)

    needs_review is a *terminal-but-recoverable* state: the audio was produced
    but failed the QC gate, so it is held for a human decision (approve/reject)
    rather than silently shipped.
    """
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    needs_review = "needs_review"
    failed = "failed"
    canceled = "canceled"


TERMINAL_STATUSES = {JobStatus.succeeded, JobStatus.needs_review, JobStatus.failed, JobStatus.canceled}


class QCPolicy(str, enum.Enum):
    off = "off"      # never gate on QC
    warn = "warn"    # record warnings, always succeed (default; current behavior)
    block = "block"  # hold jobs with failing chapters in needs_review


class ChapterStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    skipped = "skipped"
    failed = "failed"


# --------------------------------------------------------------------------- #
# Identity & tenancy
# --------------------------------------------------------------------------- #
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Monthly paid-synthesis quota in characters. 0 or NULL = use the global
    # default (QUOTA_MONTHLY_CHARS env). Free providers never count against it.
    monthly_char_quota: Mapped[Optional[int]] = mapped_column(Integer)
    # QC policy override for this org: NULL = global QC_POLICY env; else off|warn|block.
    qc_policy: Mapped[Optional[str]] = mapped_column(String(10))
    # Retention override in days for this org's job assets. NULL = global default.
    retention_days: Mapped[Optional[int]] = mapped_column(Integer)

    memberships: Mapped[List["Membership"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[List["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[List["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_user_org"),)

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), default=Role.member, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="memberships")


# --------------------------------------------------------------------------- #
# Domain
# --------------------------------------------------------------------------- #
class Project(Base):
    """A book/manuscript owned by an organization."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500), default="Untitled", nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(300))
    source_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    jobs: Mapped[List["Job"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Job(Base):
    """A durable production run. Replaces the in-memory active_tasks entry.

    Queue columns (`status`, `available_at`, `locked_by`, `locked_at`) are what
    the Postgres-backed worker claims with FOR UPDATE SKIP LOCKED.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        # The worker's claim query orders by (available_at) over queued rows.
        Index("ix_jobs_claim", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"))

    # Synthesis parameters
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(120), nullable=False)
    engine: Mapped[str] = mapped_column(String(30), default="neural", nullable=False)
    formats: Mapped[str] = mapped_column(String(60), default="mp3,m4b", nullable=False)  # comma-separated

    # State machine
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False, length=20), default=JobStatus.queued, nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chapters_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_chapter: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    synthesized_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)

    # Outputs. *_key are object-storage keys (the durable, portable reference).
    # The legacy *_path columns are kept for back-compat during the transition
    # to object storage and may be null once fully migrated.
    output_mp3: Mapped[Optional[str]] = mapped_column(Text)  # legacy local path
    output_m4b: Mapped[Optional[str]] = mapped_column(Text)  # legacy local path
    output_mp3_key: Mapped[Optional[str]] = mapped_column(Text)
    output_m4b_key: Mapped[Optional[str]] = mapped_column(Text)

    # Queue / retry bookkeeping
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_by: Mapped[Optional[str]] = mapped_column(String(100))
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="jobs")
    chapters: Mapped[List["ChapterResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ChapterResult.index"
    )
    attempt_records: Mapped[List["JobAttempt"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def format_list(self) -> List[str]:
        return [f for f in (self.formats or "").split(",") if f]

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class ChapterResult(Base):
    """Per-chapter state + QC, persisted so restarts don't lose progress."""
    __tablename__ = "chapter_results"
    __table_args__ = (UniqueConstraint("job_id", "index", name="uq_job_chapter_index"),)

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(GUID, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[ChapterStatus] = mapped_column(Enum(ChapterStatus, native_enum=False, length=20), default=ChapterStatus.pending, nullable=False)
    cached_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # QC results (nullable until the chapter is assembled)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    loudness_dbfs: Mapped[Optional[float]] = mapped_column(Float)
    peak_dbfs: Mapped[Optional[float]] = mapped_column(Float)
    silence_ratio: Mapped[Optional[float]] = mapped_column(Float)
    clipping: Mapped[Optional[bool]] = mapped_column(Boolean)
    qc_passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    qc_issues: Mapped[Optional[str]] = mapped_column(Text)  # newline-joined

    # Durable chapter artifacts (P0.2)
    audio_key: Mapped[Optional[str]] = mapped_column(String(512))
    audio_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    audio_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    synthesis_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    job: Mapped["Job"] = relationship(back_populates="chapters")


class JobAttempt(Base):
    """Audit trail of each worker attempt (blueprint: attempt state model)."""
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(GUID, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[Optional[str]] = mapped_column(String(30))  # succeeded | failed | orphaned
    error: Mapped[Optional[str]] = mapped_column(Text)

    job: Mapped["Job"] = relationship(back_populates="attempt_records")


class UsageEvent(Base):
    """Cost ledger: one row per synthesized (billable) chunk.

    ``period`` is the YYYY-MM month bucket used for monthly quota checks and
    rollups, so we can enforce limits without scanning the whole table.
    """
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_org_period", "organization_id", "period"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RateBucket(Base):
    """Fixed-window rate-limit counter for the Postgres limiter backend.

    One row per (key, window_start). The Upstash backend uses Redis instead and
    ignores this table.
    """
    __tablename__ = "rate_buckets"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[int] = mapped_column(Integer, primary_key=True)  # epoch seconds
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
