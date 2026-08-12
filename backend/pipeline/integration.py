"""Integration bridge between the existing synthesis worker and the VoxEngine
multi-agent pipeline.

When PIPELINE_ENABLED=true, the worker calls this module to preprocess chapters
through the 5-agent pipeline before synthesis. When disabled (default), the
worker uses the existing TextProcessor as before.

Usage in jobs/pipeline.py:
    from pipeline.integration import preprocess_chapter_pipeline

    if pipeline_enabled():
        clean_text, metadata = preprocess_chapter_pipeline(
            session, job.id, i, chapter["text"], chapter["title"]
        )
    else:
        clean_text = _text.preprocess_text(chapter["text"])
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from db.voxengine_models import PipelineTrace, CharacterVoiceMap, PronunciationLexicon
from sqlalchemy import select

logger = logging.getLogger("acx.pipeline.integration")

PIPELINE_ENABLED = os.getenv("PIPELINE_ENABLED", "false").lower() == "true"


def pipeline_enabled() -> bool:
    """Check if the multi-agent pipeline is enabled."""
    return PIPELINE_ENABLED


def preprocess_chapter_pipeline(
    session: Session,
    job_id: str,
    chapter_number: int,
    chapter_text: str,
    chapter_title: str = "",
) -> tuple[str, dict[str, Any]]:
    """Run a chapter through the multi-agent pipeline synchronously.

    This is the synchronous (non-Celery) path for use inside the existing
    worker. It runs all 5 agents in sequence, same as the Celery task but
    without the broker overhead.

    Returns:
        (tagged_text, metadata) where tagged_text is the fully tagged script
        and metadata contains QA results, costs, and agent timings.
    """
    from pipeline.agents.structure_parser import StructureParser
    from pipeline.agents.character_attribution import CharacterAttribution
    from pipeline.agents.text_normalizer import TextNormalizer
    from pipeline.agents.prosody_planner import ProsodyPlanner
    from pipeline.agents.qa_validator import QAValidator

    start = time.monotonic()

    # Load context from DB
    context = _load_context(session, job_id)

    # Create pipeline trace
    trace = PipelineTrace(
        job_id=job_id,
        chapter_number=chapter_number,
        status="running",
        current_agent="structure_parser",
    )
    session.add(trace)
    session.flush()

    from pipeline.agents.base import fallback_result

    degraded_stages: list[str] = []

    def _basic_fallback(stage: str, error: str | None, error_code: str | None):
        """Required stage failed: surface it, then degrade to TextProcessor."""
        trace.status = "failed"
        trace.error = f"{stage}: {error}"
        session.commit()
        logger.warning(
            "Pipeline degraded to basic preprocessing for chapter %s "
            "(stage=%s error_code=%s): %s",
            chapter_number, stage, error_code, error,
        )
        from services.text_processor import TextProcessor
        return TextProcessor().preprocess_text(chapter_text), {
            "pipeline": False,
            "degraded_stages": degraded_stages + [stage],
            "error": error,
            "error_code": error_code,
        }

    try:
        # Agent 1: Structure Parser — REQUIRED. Without structure there is
        # nothing for later stages to consume.
        agent1 = StructureParser()
        r1 = agent1.timed_run({"text": chapter_text}, context)
        trace.agent1_ms = r1.duration_ms
        if not r1.success:
            return _basic_fallback("structure_parser", r1.error, r1.error_code)

        trace.current_agent = "character_attribution"
        session.flush()

        # Agent 2: Character Attribution — OPTIONAL. Failure means we keep
        # the structure parser's chapters and the context's character list:
        # a typed fallback, never a different object type.
        agent2 = CharacterAttribution()
        r2 = agent2.timed_run({"chapters": r1.data["chapters"]}, context)
        if not r2.success:
            r2 = fallback_result(
                "character_attribution", r2.error or "failed",
                fallback_data={
                    "chapters": r1.data["chapters"],
                    "characters": context.get("characters", []),
                },
                duration_ms=r2.duration_ms,
                error_code=r2.error_code or "agent_failed",
            )
            degraded_stages.append("character_attribution")
        trace.agent2_ms = r2.duration_ms
        trace.agent2_cost_usd = r2.cost_usd
        chapters = r2.effective_data.get("chapters", r1.data["chapters"])
        context["characters"] = r2.effective_data.get(
            "characters", context.get("characters", []))

        trace.current_agent = "text_normalizer"
        session.flush()

        # Agent 3: Text Normalizer — REQUIRED. Unnormalized text produces
        # wrong pronunciations; do not pretend it succeeded.
        agent3 = TextNormalizer()
        r3 = agent3.timed_run({"chapters": chapters}, context)
        trace.agent3_ms = r3.duration_ms
        trace.agent3_cost_usd = r3.cost_usd
        if not r3.success:
            return _basic_fallback("text_normalizer", r3.error, r3.error_code)
        chapters = r3.data["chapters"]

        trace.current_agent = "prosody_planner"
        session.flush()

        # Agent 4: Prosody Planner — OPTIONAL. Failure means untagged (but
        # normalized) text continues downstream.
        agent4 = ProsodyPlanner()
        r4 = agent4.timed_run({"chapters": chapters}, context)
        if not r4.success:
            r4 = fallback_result(
                "prosody_planner", r4.error or "failed",
                fallback_data={"chapters": chapters},
                duration_ms=r4.duration_ms,
                error_code=r4.error_code or "agent_failed",
            )
            degraded_stages.append("prosody_planner")
        trace.agent4_ms = r4.duration_ms
        trace.agent4_cost_usd = r4.cost_usd
        chapters = r4.effective_data.get("chapters", chapters)

        trace.current_agent = "qa_validator"
        session.flush()

        # Agent 5: QA Validator — OPTIONAL for text flow (its failure must
        # not lose the normalized text), but its absence is surfaced and
        # qa_passed is False, never silently True.
        agent5 = QAValidator()
        context["original_chapters"] = r1.data["chapters"]
        r5 = agent5.timed_run({"chapters": chapters}, context)
        if not r5.success:
            r5 = fallback_result(
                "qa_validator", r5.error or "failed",
                fallback_data={"chapters": chapters, "qa_passed": False,
                               "issues": [f"qa_validator failed: {r5.error}"],
                               "completeness_score": 0.0},
                duration_ms=r5.duration_ms,
                error_code=r5.error_code or "agent_failed",
            )
            degraded_stages.append("qa_validator")
        trace.agent5_ms = r5.duration_ms
        trace.agent5_cost_usd = r5.cost_usd

        # Extract tagged text
        final_chapters = r5.effective_data.get("chapters", chapters)
        tagged_paragraphs = []
        for ch in final_chapters:
            for scene in ch.get("scenes", []):
                for para in scene.get("paragraphs", []):
                    tagged_paragraphs.append(para.get("text", ""))

        tagged_text = "\n\n".join(tagged_paragraphs)

        # Update trace
        trace.characters_in = r1.characters_in
        trace.characters_out = len(tagged_text)
        trace.qa_passed = r5.effective_data.get("qa_passed", False)
        trace.qa_issues = r5.effective_data.get("issues", [])
        trace.qa_completeness_score = r5.effective_data.get("completeness_score", 0.0)
        trace.status = "completed_degraded" if degraded_stages else "completed"
        trace.error = (
            "; ".join(f"{s} fell back" for s in degraded_stages) or None
        )
        trace.current_agent = None
        session.commit()

        total_ms = int((time.monotonic() - start) * 1000)
        total_cost = r2.cost_usd + r3.cost_usd + r4.cost_usd + r5.cost_usd

        logger.info(
            f"Pipeline: chapter {chapter_number} done in {total_ms}ms "
            f"(qa={trace.qa_passed}, cost=${total_cost:.4f}, "
            f"degraded={degraded_stages or 'none'})"
        )

        metadata = {
            "pipeline": True,
            "qa_passed": trace.qa_passed,
            "qa_issues": trace.qa_issues,
            "completeness_score": trace.qa_completeness_score,
            "total_cost_usd": total_cost,
            "total_duration_ms": total_ms,
            "characters": context.get("characters", []),
            "suggested_lexicon": r3.data.get("suggested_lexicon", []),
            "degraded_stages": degraded_stages,
            "fallback_used": bool(degraded_stages),
        }

        return tagged_text, metadata

    except Exception as exc:
        # Last-resort guard. With every stage explicitly checked above this
        # should not fire; if it does, the degradation is still surfaced.
        trace.status = "failed"
        trace.error = str(exc)
        session.commit()
        logger.exception(f"Pipeline failed for chapter {chapter_number}")
        from services.text_processor import TextProcessor
        return TextProcessor().preprocess_text(chapter_text), {
            "pipeline": False,
            "degraded_stages": degraded_stages,
            "error": str(exc),
            "error_code": "unexpected_exception",
        }


def _load_context(session: Session, job_id: str) -> dict[str, Any]:
    """Load project context for the pipeline."""
    from db.models import Job

    job = session.get(Job, job_id)
    if not job:
        return {}

    project_id = job.project_id

    # Character voice map
    chars = session.execute(
        select(CharacterVoiceMap).where(CharacterVoiceMap.project_id == project_id)
    ).scalars().all()
    character_map = {
        c.character_name: {
            "voice_id": c.voice_id,
            "voice_slug": c.voice_slug,
            "base_emotion": c.base_emotion,
        }
        for c in chars
    }

    # Pronunciation lexicon
    lex_entries = session.execute(
        select(PronunciationLexicon).where(PronunciationLexicon.project_id == project_id)
    ).scalars().all()
    lexicon = [
        {"word": e.word, "ipa_phoneme": e.ipa_phoneme, "phonetic_spelling": e.phonetic_spelling}
        for e in lex_entries
    ]

    return {
        "character_map": character_map,
        "lexicon": lexicon,
        "characters": list(character_map.keys()),
        "job_id": job_id,
        "project_id": project_id,
    }
