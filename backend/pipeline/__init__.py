"""VoxEngine multi-agent pipeline — Celery application and task definitions.

This module defines the Celery app for the 5-agent LLM preprocessing pipeline.
The pipeline transforms raw manuscript text into fully tagged, synthesis-ready
scripts with character attribution, pronunciation normalization, prosody tags,
and QA validation.

Architecture:
    Redis = Celery broker (for LLM pipeline only)
    PostgreSQL = synthesis job queue (existing, unchanged)
    Each chapter = one Celery task
    All chapters dispatched in parallel
"""
from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "acx_pipeline",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry policy for agent tasks
    task_default_retry_delay=30,
    task_max_retries=3,
    # Result expiry: 24 hours
    result_expires=86400,
    # Task routes
    task_routes={
        "pipeline.tasks.process_chapter": {"queue": "pipeline"},
        "pipeline.tasks.preview_synthesis": {"queue": "preview"},
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["pipeline"])
