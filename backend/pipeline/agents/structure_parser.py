"""Agent 1: Document Ingest & Structure Parser (rule-based, $0 cost).

Parses raw manuscript text into structured chapters, scenes, and paragraphs.
Identifies front matter, chapter boundaries, scene breaks, and paragraph
boundaries using regex and heuristic rules. Zero LLM cost.

Input: raw manuscript text
Output: structured chapter list with scenes and paragraphs
"""
from __future__ import annotations

import re
from typing import Any

from .base import BaseAgent, AgentResult


# Common chapter heading patterns
CHAPTER_PATTERNS = [
    re.compile(r"^(?:chapter|part|prologue|epilogue|book)\s*[\d\wIVXLC]+", re.IGNORECASE),
    re.compile(r"^(?:CHAPTER|PART|PROLOGUE|EPILOGUE|BOOK)\s*[\dIVXLC]+"),
    re.compile(r"^(?:prologue|epilogue)$", re.IGNORECASE),
    re.compile(r"^\d+\.\s+\S"),  # "1. Title"
    re.compile(r"^[IVXLC]+\.\s+\S"),  # "IV. Title"
]

# Scene break indicators
SCENE_BREAK_PATTERNS = [
    re.compile(r"^\s*\*{3,}\s*$"),  # ***
    re.compile(r"^\s*#{3,}\s*$"),  # ###
    re.compile(r"^\s*-{3,}\s*$"),  # ---
    re.compile(r"^\s*\.{3,}\s*$"),  # ...
    re.compile(r"^\s*~{3,}\s*$"),  # ~~~
]

# Dialogue detection
DIALOGUE_PATTERN = re.compile(r'^["\u201c\u201d\u2018\u2019]')


def _is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(p.match(stripped) for p in CHAPTER_PATTERNS)


def _is_scene_break(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(p.match(stripped) for p in SCENE_BREAK_PATTERNS)


def _is_dialogue(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(DIALOGUE_PATTERN.match(stripped))


def _detect_speaker_attribution(line: str) -> str | None:
    """Try to extract a speaker name from dialogue attribution.

    Looks for patterns like: "Hello," said John. / "Hello." John shook his head.
    """
    stripped = line.strip()
    # After closing quote + punctuation: "said X" or "X said"
    attr_patterns = [
        re.compile(r'[,.!?]["\u201c\u201d]\s+(?:said|asked|replied|whispered|shouted|exclaimed|muttered|answered|called|cried|began|continued|added|insisted|demanded|suggested|offered|admitted|agreed|argued|claimed|complained|explained|groaned|hissed|laughed|moaned|mumbled|murmured|nagged|objected|pleaded|promised|protested|repeated|responded|retorted|roared|screamed|sighed|snapped|snarled|sobbed|stammered|urged|warned|wept|whimpered|yelled)\s+(\w+)'),
        re.compile(r'[,.!?]["\u201c\u201d]\s+(\w+)\s+(?:said|asked|replied|whispered|shouted)'),
        re.compile(r'[,.!?]["\u201c\u201d]\s+(\w+)\s+(?:nodded|shook|smiled|laughed|frowned|sighed|grimaced|stared|glared|grinned)'),
    ]
    for p in attr_patterns:
        m = p.search(stripped)
        if m:
            return m.group(1).capitalize()
    return None


class StructureParser(BaseAgent):
    """Rule-based document structure parser. Zero LLM cost."""

    name = "structure_parser"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        text = input_data.get("text", "")
        if not text.strip():
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                error="Empty input text",
            )

        lines = text.split("\n")
        chapters: list[dict[str, Any]] = []
        current_chapter: dict[str, Any] | None = None
        current_scene: dict[str, Any] | None = None
        current_paragraph_lines: list[str] = []
        front_matter_lines: list[str] = []
        in_front_matter = True
        paragraph_index = 0

        def flush_paragraph():
            nonlocal paragraph_index
            if current_paragraph_lines and current_scene is not None:
                para_text = "\n".join(current_paragraph_lines).strip()
                if para_text:
                    is_dialogue = _is_dialogue(para_text)
                    speaker = _detect_speaker_attribution(para_text) if is_dialogue else None
                    current_scene["paragraphs"].append({
                        "index": paragraph_index,
                        "text": para_text,
                        "is_dialogue": is_dialogue,
                        "speaker_hint": speaker,
                    })
                    paragraph_index += 1
            current_paragraph_lines.clear()

        def start_new_scene():
            nonlocal current_scene, paragraph_index
            flush_paragraph()
            if current_chapter is not None:
                if current_scene is not None:
                    current_chapter["scenes"].append(current_scene)
                current_scene = {
                    "scene_index": len(current_chapter["scenes"]),
                    "paragraphs": [],
                }
                paragraph_index = 0

        for line in lines:
            # Check for chapter heading
            if _is_chapter_heading(line):
                flush_paragraph()
                if current_chapter is not None and current_scene is not None:
                    current_chapter["scenes"].append(current_scene)
                if current_chapter is not None:
                    chapters.append(current_chapter)

                in_front_matter = False
                current_chapter = {
                    "chapter_number": len(chapters) + 1,
                    "title": line.strip(),
                    "scenes": [],
                }
                current_scene = {
                    "scene_index": 0,
                    "paragraphs": [],
                }
                paragraph_index = 0
                continue

            # Before first chapter: front matter
            if in_front_matter:
                front_matter_lines.append(line)
                continue

            # Scene break
            if _is_scene_break(line):
                start_new_scene()
                continue

            # Empty line = paragraph boundary
            if not line.strip():
                flush_paragraph()
                continue

            # Accumulate paragraph lines
            current_paragraph_lines.append(line)

        # Flush remaining
        flush_paragraph()
        if current_chapter is not None and current_scene is not None:
            current_chapter["scenes"].append(current_scene)
        if current_chapter is not None:
            chapters.append(current_chapter)

        # If no chapters detected, treat the whole text as one chapter
        if not chapters:
            paragraphs = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped:
                    is_dialogue = _is_dialogue(stripped)
                    speaker = _detect_speaker_attribution(stripped) if is_dialogue else None
                    paragraphs.append({
                        "index": i,
                        "text": stripped,
                        "is_dialogue": is_dialogue,
                        "speaker_hint": speaker,
                    })
            chapters = [{
                "chapter_number": 1,
                "title": "Chapter 1",
                "scenes": [{"scene_index": 0, "paragraphs": paragraphs}],
            }]

        # Calculate stats
        total_paragraphs = sum(
            len(s["paragraphs"])
            for ch in chapters
            for s in ch["scenes"]
        )
        total_dialogue = sum(
            1
            for ch in chapters
            for s in ch["scenes"]
            for p in s["paragraphs"]
            if p["is_dialogue"]
        )

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "chapters": chapters,
                "front_matter": "\n".join(front_matter_lines).strip(),
                "stats": {
                    "chapter_count": len(chapters),
                    "total_paragraphs": total_paragraphs,
                    "total_dialogue_paragraphs": total_dialogue,
                    "total_characters": len(text),
                },
            },
            characters_in=len(text),
            characters_out=len(text),
        )
