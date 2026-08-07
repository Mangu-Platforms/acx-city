"""Agent 2: Character Attribution Engine.

Identifies speakers for dialogue paragraphs and classifies text as
narration vs dialogue. Uses Llama-3.2-3B via Ollama (self-hosted, ~$0.05/1M chars)
or DeepSeek-R1-Distill as fallback.

Input: structured chapters from Agent 1
Output: chapters with speaker attribution per paragraph
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import BaseAgent, AgentResult

logger = logging.getLogger("acx.pipeline.agent2")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
AGENT2_MODEL = os.getenv("AGENT2_MODEL", "llama3.2:3b")
AGENT2_FALLBACK_MODEL = os.getenv("AGENT2_FALLBACK_MODEL", "deepseek-r1:1.5b")

SYSTEM_PROMPT = """You are a character attribution engine for audiobook production.
Given a passage of text, identify all characters mentioned or speaking.

Rules:
1. For dialogue lines (in quotes), identify the speaker.
2. For narration, classify as "narrator".
3. Return a JSON object mapping paragraph indices to speaker names.
4. Use consistent character names (e.g., always "Sarah" not "sarah" or "Mrs. Smith").
5. If the speaker is ambiguous, use "unknown".
6. Characters should be proper nouns when available.

Return ONLY valid JSON, no explanation."""

USER_PROMPT_TEMPLATE = """Analyze these paragraphs and identify the speaker for each.

Paragraphs:
{paragraphs}

Return a JSON object mapping paragraph index to speaker name.
Example: {{"0": "narrator", "1": "Sarah", "2": "narrator", "3": "John"}}

Return ONLY the JSON object."""


def _call_ollama(prompt: str, model: str, timeout: int = 120) -> str | None:
    """Call Ollama API for text generation."""
    try:
        resp = httpx.post(
            f"{OLLAMA_ENDPOINT}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "system": SYSTEM_PROMPT,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 2048,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as exc:
        logger.warning(f"Ollama call failed ({model}): {exc}")
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response (may be wrapped in markdown)."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    import re
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... }
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _estimate_cost(text: str, model: str) -> float:
    """Estimate cost in USD for LLM processing."""
    # Rough estimate: ~4 chars per token
    tokens = len(text) / 4
    if "gpt-4o-mini" in model:
        return (tokens / 1_000_000) * 0.15
    elif "llama" in model.lower() or "deepseek" in model.lower():
        # Self-hosted: ~$0.05/1M tokens
        return (tokens / 1_000_000) * 0.05
    return 0.0


class CharacterAttribution(BaseAgent):
    """LLM-powered character attribution engine."""

    name = "character_attribution"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        chapters = input_data.get("chapters", [])
        if not chapters:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                error="No chapters in input",
            )

        all_characters: set[str] = set()
        attributed_chapters = []
        total_cost = 0.0
        total_chars_in = 0

        for chapter in chapters:
            attributed_scenes = []
            for scene in chapter.get("scenes", []):
                paragraphs = scene.get("paragraphs", [])
                if not paragraphs:
                    attributed_scenes.append(scene)
                    continue

                # Build paragraph text for LLM
                para_text = "\n".join(
                    f"[{p['index']}] {'[DIALOGUE] ' if p.get('is_dialogue') else '[NARRATION] '}{p['text'][:200]}"
                    for p in paragraphs
                )
                total_chars_in += len(para_text)

                # Call LLM for attribution
                prompt = USER_PROMPT_TEMPLATE.format(paragraphs=para_text)
                response = _call_ollama(prompt, AGENT2_MODEL)

                if response is None:
                    # Try fallback model
                    response = _call_ollama(prompt, AGENT2_FALLBACK_MODEL)

                attributions: dict[str, str] = {}
                if response:
                    parsed = _extract_json(response)
                    if parsed:
                        attributions = {str(k): str(v) for k, v in parsed.items()}

                # Merge attributions into paragraphs
                attributed_paragraphs = []
                for p in paragraphs:
                    idx_str = str(p["index"])
                    speaker = attributions.get(idx_str)
                    if speaker is None:
                        # Fallback: use hint from structure parser
                        speaker = p.get("speaker_hint") or ("narrator" if not p.get("is_dialogue") else "unknown")
                    speaker = speaker.strip().capitalize()
                    all_characters.add(speaker)
                    attributed_paragraphs.append({
                        **p,
                        "speaker": speaker,
                    })

                attributed_scenes.append({
                    **scene,
                    "paragraphs": attributed_paragraphs,
                })

                total_cost += _estimate_cost(para_text, AGENT2_MODEL)

            attributed_chapters.append({
                **chapter,
                "scenes": attributed_scenes,
            })

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "chapters": attributed_chapters,
                "characters": sorted(all_characters),
                "character_count": len(all_characters),
            },
            cost_usd=total_cost,
            characters_in=total_chars_in,
            characters_out=total_chars_in,
        )
