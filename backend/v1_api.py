"""FastAPI sidecar for VoxEngine pipeline endpoints.

This runs alongside the Flask API. NGINX routes /v1/* here and /api/* to Flask.
Gradual migration — Flask handles existing routes, FastAPI handles new pipeline.

Run: uvicorn v1_api:app --host 0.0.0.0 --port 5001
"""
from __future__ import annotations

import os
import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.session import get_session, session_scope
from db.models import Job, JobStatus, Project, ChapterResult
from db.voxengine_models import (
    PipelineTrace,
    CharacterVoiceMap,
    PronunciationLexicon,
    VoiceClone,
    StockVoice,
)
from pipeline.tasks import process_chapter, process_book

logger = logging.getLogger("acx.v1")

app = FastAPI(
    title="ACX City VoxEngine API",
    description="Multi-agent pipeline, voice catalog, and studio endpoints",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Request/Response models
# --------------------------------------------------------------------------- #

class PipelineStartRequest(BaseModel):
    """Start multi-agent preprocessing for a project."""
    force: bool = False  # Re-process even if already processed


class PipelineStatusResponse(BaseModel):
    job_id: str
    status: str
    chapters_total: int
    chapters_completed: int
    chapters_failed: int
    total_cost_usd: float
    traces: list[dict[str, Any]]


class CharacterVoiceRequest(BaseModel):
    character_name: str
    voice_id: Optional[str] = None
    voice_slug: Optional[str] = None
    pitch_adjustment: float = 1.0
    speed_adjustment: float = 1.0
    base_emotion: str = "neutral"
    is_narrator: bool = False
    notes: Optional[str] = None


class LexiconEntryRequest(BaseModel):
    word: str
    ipa_phoneme: Optional[str] = None
    phonetic_spelling: Optional[str] = None
    context_note: Optional[str] = None
    is_global: bool = False


class PreviewRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None
    voice_slug: Optional[str] = "en-US-AriaNeural"
    emotion: Optional[str] = None
    duration_seconds: float = 5.0


class RerenderRequest(BaseModel):
    paragraph_start: Optional[int] = None
    paragraph_end: Optional[int] = None


# --------------------------------------------------------------------------- #
# Pipeline endpoints
# --------------------------------------------------------------------------- #

@app.post("/v1/projects/{project_id}/pipeline/start")
async def start_pipeline(project_id: str, req: PipelineStartRequest):
    """Kick off multi-agent preprocessing for all chapters in a project."""
    with session_scope() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        # Get the latest job for this project
        job = db.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .where(Job.status.in_([JobStatus.queued, JobStatus.running]))
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not job:
            raise HTTPException(400, "No active job found for this project")

        # Split source text into chapters (simple split by double newline for now)
        source_text = project.source_text or ""
        if not source_text.strip():
            raise HTTPException(400, "Project has no source text")

        # Use the structure parser to split into chapters
        from pipeline.agents.structure_parser import StructureParser
        parser = StructureParser()
        result = parser.timed_run({"text": source_text}, {})
        if not result.success:
            raise HTTPException(500, f"Structure parsing failed: {result.error}")

        chapters_data = []
        for ch in result.data["chapters"]:
            chapter_text = "\n\n".join(
                p["text"]
                for s in ch["scenes"]
                for p in s["paragraphs"]
            )
            chapters_data.append({
                "chapter_number": ch["chapter_number"],
                "text": chapter_text,
                "title": ch.get("title", f"Chapter {ch['chapter_number']}"),
            })

        # Dispatch to Celery
        task_result = process_book.delay(job.id, chapters_data)

        return {
            "job_id": job.id,
            "task_id": task_result.id,
            "chapters_dispatched": len(chapters_data),
            "status": "processing",
        }


@app.get("/v1/projects/{project_id}/pipeline/status")
async def pipeline_status(project_id: str):
    """Get per-chapter pipeline status and costs."""
    with session_scope() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        # Get latest job
        job = db.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not job:
            raise HTTPException(404, "No job found for this project")

        traces = db.execute(
            select(PipelineTrace)
            .where(PipelineTrace.job_id == job.id)
            .order_by(PipelineTrace.chapter_number)
        ).scalars().all()

        completed = sum(1 for t in traces if t.status == "completed")
        failed = sum(1 for t in traces if t.status == "failed")
        total_cost = sum(
            float(t.agent2_cost_usd or 0) +
            float(t.agent3_cost_usd or 0) +
            float(t.agent4_cost_usd or 0) +
            float(t.agent5_cost_usd or 0)
            for t in traces
        )

        return {
            "job_id": job.id,
            "status": job.status.value,
            "chapters_total": len(traces),
            "chapters_completed": completed,
            "chapters_failed": failed,
            "total_cost_usd": round(total_cost, 6),
            "traces": [
                {
                    "chapter_number": t.chapter_number,
                    "status": t.status,
                    "current_agent": t.current_agent,
                    "agent1_ms": t.agent1_ms,
                    "agent2_ms": t.agent2_ms,
                    "agent3_ms": t.agent3_ms,
                    "agent4_ms": t.agent4_ms,
                    "agent5_ms": t.agent5_ms,
                    "qa_passed": t.qa_passed,
                    "qa_completeness_score": t.qa_completeness_score,
                    "error": t.error,
                }
                for t in traces
            ],
        }


@app.get("/v1/projects/{project_id}/pipeline/trace/{chapter_number}")
async def pipeline_trace(project_id: str, chapter_number: int):
    """Get full agent trace for a specific chapter."""
    with session_scope() as db:
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        job = db.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not job:
            raise HTTPException(404, "No job found")

        trace = db.execute(
            select(PipelineTrace)
            .where(PipelineTrace.job_id == job.id)
            .where(PipelineTrace.chapter_number == chapter_number)
        ).scalar_one_or_none()

        if not trace:
            raise HTTPException(404, f"No trace found for chapter {chapter_number}")

        return {
            "id": trace.id,
            "job_id": trace.job_id,
            "chapter_number": trace.chapter_number,
            "status": trace.status,
            "current_agent": trace.current_agent,
            "agents": {
                "structure_parser": {"ms": trace.agent1_ms},
                "character_attribution": {"ms": trace.agent2_ms, "cost_usd": float(trace.agent2_cost_usd or 0)},
                "text_normalizer": {"ms": trace.agent3_ms, "cost_usd": float(trace.agent3_cost_usd or 0)},
                "prosody_planner": {"ms": trace.agent4_ms, "cost_usd": float(trace.agent4_cost_usd or 0)},
                "qa_validator": {"ms": trace.agent5_ms, "cost_usd": float(trace.agent5_cost_usd or 0)},
            },
            "characters_in": trace.characters_in,
            "characters_out": trace.characters_out,
            "qa_passed": trace.qa_passed,
            "qa_issues": trace.qa_issues,
            "qa_completeness_score": trace.qa_completeness_score,
            "error": trace.error,
        }


# --------------------------------------------------------------------------- #
# Character Voice Map endpoints
# --------------------------------------------------------------------------- #

@app.get("/v1/projects/{project_id}/characters")
async def list_characters(project_id: str):
    """Get character voice assignments for a project."""
    with session_scope() as db:
        chars = db.execute(
            select(CharacterVoiceMap)
            .where(CharacterVoiceMap.project_id == project_id)
            .order_by(CharacterVoiceMap.is_narrator.desc(), CharacterVoiceMap.character_name)
        ).scalars().all()

        return [
            {
                "id": c.id,
                "character_name": c.character_name,
                "voice_id": c.voice_id,
                "voice_slug": c.voice_slug,
                "pitch_adjustment": float(c.pitch_adjustment or 1.0),
                "speed_adjustment": float(c.speed_adjustment or 1.0),
                "base_emotion": c.base_emotion,
                "is_narrator": c.is_narrator,
                "attribution_confidence": c.attribution_confidence,
                "notes": c.notes,
            }
            for c in chars
        ]


@app.post("/v1/projects/{project_id}/characters")
async def set_character(project_id: str, req: CharacterVoiceRequest):
    """Set or update a character voice assignment."""
    with session_scope() as db:
        existing = db.execute(
            select(CharacterVoiceMap)
            .where(CharacterVoiceMap.project_id == project_id)
            .where(CharacterVoiceMap.character_name == req.character_name)
        ).scalar_one_or_none()

        if existing:
            existing.voice_id = req.voice_id
            existing.voice_slug = req.voice_slug
            existing.pitch_adjustment = req.pitch_adjustment
            existing.speed_adjustment = req.speed_adjustment
            existing.base_emotion = req.base_emotion
            existing.is_narrator = req.is_narrator
            existing.notes = req.notes
            return {"id": existing.id, "updated": True}

        char = CharacterVoiceMap(
            project_id=project_id,
            character_name=req.character_name,
            voice_id=req.voice_id,
            voice_slug=req.voice_slug,
            pitch_adjustment=req.pitch_adjustment,
            speed_adjustment=req.speed_adjustment,
            base_emotion=req.base_emotion,
            is_narrator=req.is_narrator,
            notes=req.notes,
        )
        db.add(char)
        db.flush()
        return {"id": char.id, "created": True}


# --------------------------------------------------------------------------- #
# Pronunciation Lexicon endpoints
# --------------------------------------------------------------------------- #

@app.get("/v1/projects/{project_id}/lexicon")
async def list_lexicon(project_id: str):
    """Get pronunciation lexicon for a project."""
    with session_scope() as db:
        entries = db.execute(
            select(PronunciationLexicon)
            .where(PronunciationLexicon.project_id == project_id)
            .order_by(PronunciationLexicon.word)
        ).scalars().all()

        return [
            {
                "id": e.id,
                "word": e.word,
                "ipa_phoneme": e.ipa_phoneme,
                "phonetic_spelling": e.phonetic_spelling,
                "context_note": e.context_note,
                "source": e.source,
                "is_global": e.is_global,
            }
            for e in entries
        ]


@app.post("/v1/projects/{project_id}/lexicon")
async def add_lexicon_entry(project_id: str, req: LexiconEntryRequest):
    """Add a pronunciation lexicon entry."""
    with session_scope() as db:
        existing = db.execute(
            select(PronunciationLexicon)
            .where(PronunciationLexicon.project_id == project_id)
            .where(PronunciationLexicon.word == req.word)
        ).scalar_one_or_none()

        if existing:
            existing.ipa_phoneme = req.ipa_phoneme
            existing.phonetic_spelling = req.phonetic_spelling
            existing.context_note = req.context_note
            existing.is_global = req.is_global
            return {"id": existing.id, "updated": True}

        entry = PronunciationLexicon(
            project_id=project_id,
            word=req.word,
            ipa_phoneme=req.ipa_phoneme,
            phonetic_spelling=req.phonetic_spelling,
            context_note=req.context_note,
            source="manual",
            is_global=req.is_global,
        )
        db.add(entry)
        db.flush()
        return {"id": entry.id, "created": True}


@app.delete("/v1/projects/{project_id}/lexicon/{entry_id}")
async def delete_lexicon_entry(project_id: str, entry_id: str):
    """Delete a pronunciation lexicon entry."""
    with session_scope() as db:
        entry = db.get(PronunciationLexicon, entry_id)
        if not entry or entry.project_id != project_id:
            raise HTTPException(404, "Entry not found")
        db.delete(entry)
        return {"deleted": True}


# --------------------------------------------------------------------------- #
# Voice endpoints
# --------------------------------------------------------------------------- #

@app.get("/v1/voices")
async def list_voices(
    provider: Optional[str] = None,
    gender: Optional[str] = None,
    accent: Optional[str] = None,
    is_active: bool = True,
    limit: int = 50,
    offset: int = 0,
):
    """Browse the stock voice catalog with filters."""
    with session_scope() as db:
        query = select(StockVoice).where(StockVoice.is_active == is_active)
        if provider:
            query = query.where(StockVoice.provider == provider)
        if gender:
            query = query.where(StockVoice.gender == gender)
        if accent:
            query = query.where(StockVoice.accent == accent)

        query = query.order_by(StockVoice.display_name).offset(offset).limit(min(limit, 200))
        voices = db.execute(query).scalars().all()

        return [
            {
                "id": v.id,
                "slug": v.slug,
                "display_name": v.display_name,
                "gender": v.gender,
                "accent": v.accent,
                "age_range": v.age_range,
                "style_tags": v.style_tags,
                "description": v.description,
                "provider": v.provider,
                "sample_audio_url": v.sample_audio_url,
                "languages": v.languages,
                "emotion_tags": v.emotion_tags,
                "is_cloneable": v.is_cloneable,
            }
            for v in voices
        ]


@app.get("/v1/voices/{voice_id}")
async def get_voice(voice_id: str):
    """Get voice detail with emotion tags and sample URL."""
    with session_scope() as db:
        voice = db.get(StockVoice, voice_id)
        if not voice:
            raise HTTPException(404, "Voice not found")
        return {
            "id": voice.id,
            "slug": voice.slug,
            "display_name": voice.display_name,
            "gender": voice.gender,
            "accent": voice.accent,
            "age_range": voice.age_range,
            "style_tags": voice.style_tags,
            "description": voice.description,
            "provider": voice.provider,
            "provider_voice_id": voice.provider_voice_id,
            "sample_audio_url": voice.sample_audio_url,
            "languages": voice.languages,
            "emotion_tags": voice.emotion_tags,
            "is_cloneable": voice.is_cloneable,
            "source": voice.source,
        }


# --------------------------------------------------------------------------- #
# Chapter re-render endpoint
# --------------------------------------------------------------------------- #

@app.post("/v1/chapters/{chapter_id}/rerender")
async def rerender_chapter(chapter_id: str, req: RerenderRequest):
    """Re-render a single chapter (or paragraph range) through the pipeline."""
    with session_scope() as db:
        chapter = db.get(ChapterResult, chapter_id)
        if not chapter:
            raise HTTPException(404, "Chapter not found")

        job = db.get(Job, chapter.job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        # Get project source text
        project = db.get(Project, job.project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        # Dispatch re-render
        task = process_chapter.delay(
            job_id=job.id,
            chapter_number=chapter.index,
            chapter_text=project.source_text,  # Simplified; in production, extract just this chapter
            chapter_title=chapter.title or f"Chapter {chapter.index}",
        )

        return {
            "chapter_id": chapter_id,
            "task_id": task.id,
            "status": "rerendering",
        }


# --------------------------------------------------------------------------- #
# Waveform endpoint
# --------------------------------------------------------------------------- #

@app.get("/v1/chapters/{chapter_id}/waveform")
async def get_waveform(chapter_id: str):
    """Get waveform JSON for WaveSurfer.js rendering."""
    with session_scope() as db:
        chapter = db.get(ChapterResult, chapter_id)
        if not chapter:
            raise HTTPException(404, "Chapter not found")

        # Waveform data would be pre-computed and stored
        # For now, return a placeholder
        return {
            "chapter_id": chapter_id,
            "duration_seconds": chapter.duration_seconds,
            "sample_rate": 24000,
            "peaks": [],  # Would be chunked peak data
            "markers": [],  # Chapter markers, speaker changes
        }


# --------------------------------------------------------------------------- #
# Voice clone endpoints
# --------------------------------------------------------------------------- #

@app.get("/v1/voices/clones")
async def list_voice_clones(organization_id: str = Query(...)):
    """List organization's voice clones."""
    with session_scope() as db:
        clones = db.execute(
            select(VoiceClone)
            .where(VoiceClone.organization_id == organization_id)
            .order_by(VoiceClone.created_at.desc())
        ).scalars().all()

        return [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "provider": c.provider,
                "reference_duration_seconds": float(c.reference_duration_seconds or 0),
                "safety_similarity_score": c.safety_similarity_score,
                "created_at": c.created_at.isoformat(),
            }
            for c in clones
        ]


@app.post("/v1/voices/clone")
async def create_voice_clone(organization_id: str = Query(...)):
    """Upload reference audio and create a voice clone.

    TODO: Implement multipart upload, Fish Speech S2 embedding computation,
    and protected voice similarity check.
    """
    raise HTTPException(501, "Voice cloning not yet implemented — Phase 10")


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #

@app.get("/v1/health")
async def health():
    """Health check for the FastAPI sidecar."""
    return {"status": "ok", "service": "acx-city-v1", "version": "1.0.0"}
