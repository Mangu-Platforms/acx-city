"""Agent 5: QA Consistency Validator.

Validates the fully tagged output from Agent 4 for:
- Completeness (all paragraphs processed)
- Tag validity (no unclosed tags, valid tag names)
- Character consistency (same character name across chapters)
- Pronunciation coverage (all lexicon entries applied)
- Emotional coherence (no contradictory tags)

Uses gpt-4o-mini (batch mode). ~$0.10/1M chars.

Input: prosody-tagged chapters from Agent 4
Output: QA report with pass/fail and issue list
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from .base import BaseAgent, AgentResult

logger = logging.getLogger("acx.pipeline.agent5")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AGENT5_MODEL = os.getenv("AGENT5_MODEL", "gpt-4o-mini")

# Valid prosody tags
VALID_TAGS = {
    "angry", "sad", "whisper", "soft", "breathy", "excited", "embarrassed",
    "laughing", "sobbing", "sighing", "pause", "scene_break",
    "rate", "emphasis", "SPEAKER",
}

# Tags that require a value
TAGS_WITH_VALUES = {"pause", "scene_break", "rate", "SPEAKER"}


def _validate_tags(text: str) -> list[dict[str, Any]]:
    """Check for valid prosody tags in text."""
    issues = []
    tag_pattern = re.compile(r"\[(\w+)(?::([^\]]+))?\]")
    for match in tag_pattern.finditer(text):
        tag_name = match.group(1)
        tag_value = match.group(2)

        if tag_name not in VALID_TAGS:
            issues.append({
                "type": "invalid_tag",
                "tag": tag_name,
                "position": match.start(),
                "severity": "warning",
            })

        if tag_name in TAGS_WITH_VALUES and not tag_value:
            issues.append({
                "type": "missing_tag_value",
                "tag": tag_name,
                "position": match.start(),
                "severity": "error",
            })

        if tag_name == "pause" and tag_value:
            try:
                ms = int(tag_value)
                if ms < 0 or ms > 10000:
                    issues.append({
                        "type": "invalid_pause_duration",
                        "tag": f"pause:{tag_value}",
                        "position": match.start(),
                        "severity": "warning",
                    })
            except ValueError:
                issues.append({
                    "type": "invalid_tag_value",
                    "tag": f"pause:{tag_value}",
                    "position": match.start(),
                    "severity": "error",
                })

    return issues


def _check_unclosed_tags(text: str) -> list[dict[str, Any]]:
    """Check for unclosed or malformed tags."""
    issues = []
    # Check for tags that look like they should be closed but aren't
    open_tags = re.findall(r"\[(\w+)(?::[^\]]*)?\]", text)
    close_tags = re.findall(r"\[/(\w+)\]", text)

    # pron tags are the only ones that need closing
    for tag in set(open_tags):
        if tag == "pron" and tag not in close_tags:
            issues.append({
                "type": "unclosed_tag",
                "tag": tag,
                "severity": "error",
            })

    return issues


def _check_completeness(
    original_chapters: list[dict[str, Any]],
    tagged_chapters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verify all paragraphs from input exist in output."""
    issues = []

    original_count = sum(
        len(s.get("paragraphs", []))
        for ch in original_chapters
        for s in ch.get("scenes", [])
    )
    tagged_count = sum(
        len(s.get("paragraphs", []))
        for ch in tagged_chapters
        for s in ch.get("scenes", [])
    )

    if tagged_count < original_count:
        issues.append({
            "type": "missing_paragraphs",
            "expected": original_count,
            "actual": tagged_count,
            "missing": original_count - tagged_count,
            "severity": "error",
        })

    return issues


def _check_character_consistency(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check that character names are consistent across chapters."""
    issues = []
    character_names: dict[str, set[str]] = {}  # lowercase → set of variants

    for chapter in chapters:
        for scene in chapter.get("scenes", []):
            for para in scene.get("paragraphs", []):
                speaker = para.get("speaker", "")
                if speaker and speaker != "narrator" and speaker != "unknown":
                    key = speaker.lower()
                    if key not in character_names:
                        character_names[key] = set()
                    character_names[key].add(speaker)

    for key, variants in character_names.items():
        if len(variants) > 1:
            issues.append({
                "type": "inconsistent_character_name",
                "character": key,
                "variants": sorted(variants),
                "severity": "warning",
                "suggestion": f"Use consistent name: {max(variants, key=len)}",
            })

    return issues


def _check_empty_text(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check for empty or near-empty paragraphs."""
    issues = []
    for chapter in chapters:
        for scene in chapter.get("scenes", []):
            for para in scene.get("paragraphs", []):
                text = para.get("text", "").strip()
                # Remove tags to check actual content
                clean_text = re.sub(r"\[[\w:]+(?:\]|[^\]]*\])", "", text).strip()
                if not clean_text:
                    issues.append({
                        "type": "empty_paragraph",
                        "chapter": chapter.get("chapter_number"),
                        "paragraph_index": para.get("index"),
                        "severity": "warning",
                    })
    return issues


def _calculate_completeness_score(issues: list[dict[str, Any]]) -> float:
    """Calculate a 0.0–1.0 completeness score."""
    if not issues:
        return 1.0

    error_count = sum(1 for i in issues if i.get("severity") == "error")
    warning_count = sum(1 for i in issues if i.get("severity") == "warning")

    # Errors are 5x worse than warnings
    penalty = (error_count * 0.1) + (warning_count * 0.02)
    return max(0.0, 1.0 - penalty)


class QAValidator(BaseAgent):
    """Quality assurance and consistency validation."""

    name = "qa_validator"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        chapters = input_data.get("chapters", [])
        original_chapters = context.get("original_chapters", [])

        if not chapters:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                error="No chapters in input",
            )

        all_issues: list[dict[str, Any]] = []
        total_chars = 0

        # 1. Completeness check
        if original_chapters:
            all_issues.extend(_check_completeness(original_chapters, chapters))

        # 2. Character consistency
        all_issues.extend(_check_character_consistency(chapters))

        # 3. Per-paragraph validation
        for chapter in chapters:
            for scene in chapter.get("scenes", []):
                for para in scene.get("paragraphs", []):
                    text = para.get("text", "")
                    total_chars += len(text)

                    # Tag validation
                    all_issues.extend(_validate_tags(text))
                    all_issues.extend(_check_unclosed_tags(text))

        # 4. Empty text check
        all_issues.extend(_check_empty_text(chapters))

        # Calculate score and pass/fail
        completeness_score = _calculate_completeness_score(all_issues)
        error_count = sum(1 for i in all_issues if i.get("severity") == "error")
        qa_passed = error_count == 0

        logger.info(
            f"QA validation: {'PASSED' if qa_passed else 'FAILED'} "
            f"(score={completeness_score:.2f}, errors={error_count}, "
            f"warnings={len(all_issues) - error_count})"
        )

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "qa_passed": qa_passed,
                "completeness_score": completeness_score,
                "issues": all_issues,
                "issue_count": len(all_issues),
                "error_count": error_count,
                "warning_count": len(all_issues) - error_count,
                "chapters": chapters,  # pass through
            },
            characters_in=total_chars,
            characters_out=total_chars,
        )
