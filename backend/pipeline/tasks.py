"""Celery tasks for the multi-agent pipeline.

Each chapter becomes one Celery task that runs through all 5 agents sequentially.
All chapters from a book are dispatched in parallel.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from celery import shared_task
from sqlalchemy import select

from db.session import session_scope
from db.models import Job, ChapterResult
from db.voxengine_models import PipelineTrace, CharacterVoiceMap, PronunciationLexicon

from .agents.structure_parser import StructureParser
from .agents.character_attribution import CharacterAttribution
from .agents.text_normalizer import TextNormalizer
from .agents.prosody_planner import ProsodyPlanner
from .agents.qa_validator import QAValidator

logger = logging.getLogger("acx.pipeline.tasks")

# Agent instances (singletons)
agent1 = StructureParser()
agent2 = CharacterAttribution()
agent3 = TextNormalizer()
agent4 = ProsodyPlanner()
agent5 = QAValidator()


def _load_context(job_id: str, session) -> dict[str, Any]:
    """Load project context: character voice map, pronunciation lexicon."""
    job = session.get(Job, job_id)
    if not job:
        return {}

    project_id = job.project_id

    # Load character voice map
    chars = session.execute(
        select(CharacterVoiceMap).where(CharacterVoiceMap.project_id == project_id)
    ).scalars().all()
    character_map = {
        c.character_name: {
            "voice_id": c.voice_id,
            "voice_slug": c.voice_slug,
            "base_emotion": c.base_emotion,
            "pitch_adjustment": float(c.pitch_adjustment or 1.0),
            "speed_adjustment": float(c.speed_adjustment or 1.0),
        }
        for c in chars
    }

    # Load pronunciation lexicon
    lex_entries = session.execute(
        select(PronunciationLexicon).where(PronunciationLexicon.project_id == project_id)
    ).scalars().all()
    lexicon = [
        {
            "word": e.word,
            "ipa_phoneme": e.ipa_phoneme,
            "phonetic_spelling": e.phonetic_spelling,
        }
        for e in lex_entries
    ]

    return {
        "character_map": character_map,
        "lexicon": lexicon,
        "characters": list(character_map.keys()),
        "job_id": job_id,
        "project_id": project_id,
    }


@shared_task(name="pipeline.tasks.process_chapter", bind=True, max_retries=3)
def process_chapter(
    self,
    job_id: str,
    chapter_number: int,
    chapter_text: str,
    chapter_title: str = "",
) -> dict[str, Any]:
    """Process a single chapter through the 5-agent pipeline.

    Args:
        job_id: The synthesis job ID
        chapter_number: Chapter number (1-indexed)
        chapter_text: Raw chapter text
        chapter_title: Chapter title/heading

    Returns:
        Pipeline result dict with tagged text, QA status, and traces
    """
    logger.info(f"Pipeline: processing chapter {chapter_number} for job {job_id}")
    start_time = time.monotonic()

    # Create or update pipeline trace
    with session_scope() as session:
        trace = PipelineTrace(
            job_id=job_id,
            chapter_number=chapter_number,
            status="running",
            current_agent="structure_parser",
        )
        session.add(trace)
        session.flush()
        trace_id = trace.id

    context: dict[str, Any] = {}
    try:
        with session_scope() as session:
            context = _load_context(job_id, session)
    except Exception:
        logger.warning(f"Could not load context for job {job_id}, proceeding with defaults")

    # --- Agent 1: Structure Parser ---
    logger.info(f"  Agent 1: Structure Parser (ch {chapter_number})")
    result1 = agent1.timed_run({"text": chapter_text}, context)
    if not result1.success:
        _update_trace(trace_id, agent1_ms=result1.duration_ms, status="failed", error=result1.error)
        return {"success": False, "error": f"Agent 1 failed: {result1.error}"}

    _update_trace(trace_id, agent1_ms=result1.duration_ms, current_agent="character_attribution")
    chapters = result1.data["chapters"]
    context["characters"] = context.get("characters", []) + result1.data.get("stats", {}).get("characters", [])

    # --- Agent 2: Character Attribution ---
    logger.info(f"  Agent 2: Character Attribution (ch {chapter_number})")
    result2 = agent2.timed_run({"chapters": chapters}, context)
    if not result2.success:
        _update_trace(trace_id, agent2_ms=result2.duration_ms, status="failed", error=result2.error)
        # Fallback: use structure parser's hints
        result2 = agent2  # Keep going with what we have

    _update_trace(
        trace_id,
        agent2_ms=result2.duration_ms,
        agent2_cost_usd=result2.cost_usd,
        current_agent="text_normalizer",
    )
    chapters = result2.data.get("chapters", chapters)
    context["characters"] = result2.data.get("characters", context.get("characters", []))

    # --- Agent 3: Text Normalizer ---
    logger.info(f"  Agent 3: Text Normalizer (ch {chapter_number})")
    result3 = agent3.timed_run({"chapters": chapters}, context)
    if not result3.success:
        _update_trace(trace_id, agent3_ms=result3.duration_ms, status="failed", error=result3.error)
        return {"success": False, "error": f"Agent 3 failed: {result3.error}"}

    _update_trace(
        trace_id,
        agent3_ms=result3.duration_ms,
        agent3_cost_usd=result3.cost_usd,
        current_agent="prosody_planner",
    )
    chapters = result3.data["chapters"]

    # --- Agent 4: Prosody Planner ---
    logger.info(f"  Agent 4: Prosody Planner (ch {chapter_number})")
    result4 = agent4.timed_run({"chapters": chapters}, context)
    if not result4.success:
        _update_trace(trace_id, agent4_ms=result4.duration_ms, status="failed", error=result4.error)
        # Fallback: continue with untagged text
        result4 = agent4

    _update_trace(
        trace_id,
        agent4_ms=result4.duration_ms,
        agent4_cost_usd=result4.cost_usd,
        current_agent="qa_validator",
    )
    chapters = result4.data.get("chapters", chapters)

    # --- Agent 5: QA Validator ---
    logger.info(f"  Agent 5: QA Validator (ch {chapter_number})")
    context["original_chapters"] = result1.data["chapters"]
    result5 = agent5.timed_run({"chapters": chapters}, context)
    if not result5.success:
        _update_trace(trace_id, agent5_ms=result5.duration_ms, status="failed", error=result5.error)
        return {"success": False, "error": f"Agent 5 failed: {result5.error}"}

    # Extract final tagged text
    final_chapters = result5.data.get("chapters", chapters)
    qa_passed = result5.data.get("qa_passed", False)
    qa_issues = result5.data.get("issues", [])
    completeness_score = result5.data.get("completeness_score", 0.0)

    # Flatten paragraphs to tagged text
    tagged_paragraphs = []
    for ch in final_chapters:
        for scene in ch.get("scenes", []):
            for para in scene.get("paragraphs", []):
                tagged_paragraphs.append(para.get("text", ""))

    tagged_text = "\n\n".join(tagged_paragraphs)

    total_duration = int((time.monotonic() - start_time) * 1000)

    # Update final trace
    _update_trace(
        trace_id,
        agent5_ms=result5.duration_ms,
        agent5_cost_usd=result5.cost_usd,
        characters_in=result1.characters_in,
        characters_out=len(tagged_text),
        qa_passed=qa_passed,
        qa_issues=qa_issues,
        qa_completeness_score=completeness_score,
        status="completed",
        current_agent=None,
    )

    # Update pipeline trace with total cost
    total_cost = (
        result2.cost_usd + result3.cost_usd + result4.cost_usd + result5.cost_usd
    )

    logger.info(
        f"Pipeline: chapter {chapter_number} complete in {total_duration}ms "
        f"(qa_passed={qa_passed}, cost=${total_cost:.4f})"
    )

    return {
        "success": True,
        "chapter_number": chapter_number,
        "tagged_text": tagged_text,
        "qa_passed": qa_passed,
        "qa_issues": qa_issues,
        "completeness_score": completeness_score,
        "total_cost_usd": total_cost,
        "total_duration_ms": total_duration,
        "agent_durations_ms": {
            "structure_parser": result1.duration_ms,
            "character_attribution": result2.duration_ms,
            "text_normalizer": result3.duration_ms,
            "prosody_planner": result4.duration_ms,
            "qa_validator": result5.duration_ms,
        },
        "characters": context.get("characters", []),
        "suggested_lexicon": result3.data.get("suggested_lexicon", []),
    }


def _update_trace(trace_id: str, **kwargs) -> None:
    """Update a pipeline trace row."""
    try:
        with session_scope() as session:
            trace = session.get(PipelineTrace, trace_id)
            if trace:
                for k, v in kwargs.items():
                    if hasattr(trace, k):
                        setattr(trace, k, v)
    except Exception as exc:
        logger.warning(f"Failed to update pipeline trace {trace_id}: {exc}")


@shared_task(name="pipeline.tasks.process_book")
def process_book(job_id: str, chapters_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Dispatch all chapters of a book in parallel through the pipeline.

    Args:
        job_id: The synthesis job ID
        chapters_data: List of {chapter_number, text, title} dicts

    Returns:
        Summary with per-chapter results
    """
    logger.info(f"Pipeline: dispatching {len(chapters_data)} chapters for job {job_id}")

    # Dispatch all chapters as parallel tasks
    results = []
    for ch in chapters_data:
        result = process_chapter.delay(
            job_id=job_id,
            chapter_number=ch["chapter_number"],
            chapter_text=ch["text"],
            chapter_title=ch.get("title", ""),
        )
        results.append({
            "chapter_number": ch["chapter_number"],
            "task_id": result.id,
        })

    return {
        "success": True,
        "job_id": job_id,
        "chapters_dispatched": len(results),
        "task_ids": results,
    }
