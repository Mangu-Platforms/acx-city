"""Agent 4: Prosody & Emotion Planner.

Inserts emotion tags, pause markers, rate changes, and emphasis cues into
normalized text. This is the intelligence layer that makes ACX City output
superior to raw TTS.

Emotion tag vocabulary (superset of fish.audio S2.1):
    [angry] [sad] [whisper] [soft] [breathy] [excited] [embarrassed]
    [laughing] [sobbing] [sighing] [pause:NNN] [scene_break:3000]
    [rate:slow] [rate:fast] [emphasis] [SPEAKER:Name]

Uses Phi-3.5-mini (primary) or Gemma-2-2B (fallback via Ollama).
~$0.08/1M chars.

Input: normalized chapters from Agent 3
Output: chapters with prosody tags inserted into text
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from .base import BaseAgent, AgentResult

logger = logging.getLogger("acx.pipeline.agent4")

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
AGENT4_MODEL = os.getenv("AGENT4_MODEL", "phi3.5:mini")
AGENT4_FALLBACK_MODEL = os.getenv("AGENT4_FALLBACK_MODEL", "gemma2:2b")

SYSTEM_PROMPT = """You are a prosody and emotion planning engine for audiobook narration.
Given text with speaker attribution, insert emotion and prosody tags to guide
text-to-speech synthesis.

Available tags (insert inline in the text):
- [angry] — raised pitch, faster rate, harder consonants
- [sad] — lower pitch, slower rate, softer delivery
- [whisper] — reduced amplitude, breathy, intimate
- [soft] — gentle volume, warm tone
- [breathy] — airy voice quality, vulnerability
- [excited] — faster rate, higher energy
- [embarrassed] — slightly slower, halting quality
- [laughing] — laugh audio insert + bright tone
- [sobbing] — interrupted delivery, catch in voice
- [sighing] — exhale insert before line
- [pause:NNN] — silence of NNN milliseconds
- [scene_break:3000] — 3-second silence + tone for scene transitions
- [rate:slow] — speaking rate -20%
- [rate:fast] — speaking rate +20%
- [emphasis] — word stress applied to next word
- [SPEAKER:Name] — switch to character's voice

Rules:
1. Don't overtag — most narration needs no tags.
2. Use tags at the START of the relevant text segment.
3. Scene breaks get [scene_break:3000].
4. Dialogue emotion should match the character's situation.
5. Internal monologue often benefits from [whisper] or [soft].
6. Action scenes use [rate:fast] and [excited].
7. Emotional peaks get [pause:500] before the key line.
8. Each paragraph should have at most 2-3 tags.

Return the text with tags inserted. Keep all original content."""

USER_PROMPT_TEMPLATE = """Add prosody and emotion tags to these paragraphs.
Character: {speaker}
Context: {context}

Paragraphs:
{paragraphs}

Return the tagged text for each paragraph, preserving the [INDEX] markers."""


def _call_ollama(prompt: str, model: str, timeout: int = 180) -> str | None:
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
                    "temperature": 0.3,
                    "num_predict": 4096,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as exc:
        logger.warning(f"Ollama call failed ({model}): {exc}")
        return None


def _estimate_cost(text: str) -> float:
    """Estimate cost for agent 4 processing."""
    tokens = len(text) / 4
    if "phi" in AGENT4_MODEL.lower():
        return (tokens / 1_000_000) * 0.08
    return (tokens / 1_000_000) * 0.08


def _apply_rule_based_tags(para: dict[str, Any]) -> str:
    """Apply rule-based prosody tags as fallback when LLM is unavailable."""
    text = para.get("text", "")
    speaker = para.get("speaker", "narrator")

    # Add speaker tag at the start
    tagged = f"[SPEAKER:{speaker}] {text}"

    # Detect emotional keywords and add tags
    lower_text = text.lower()

    if any(w in lower_text for w in ["!", "shouted", "screamed", "yelled", "roared"]):
        tagged = f"[SPEAKER:{speaker}] [angry] {text}"
    elif any(w in lower_text for w in ["whispered", "murmured", "softly", "quietly"]):
        tagged = f"[SPEAKER:{speaker}] [whisper] {text}"
    elif any(w in lower_text for w in ["cried", "sobbed", "wept", "tears"]):
        tagged = f"[SPEAKER:{speaker}] [sad] {text}"
    elif any(w in lower_text for w in ["laughed", "grinned", "chuckled", "amused"]):
        tagged = f"[SPEAKER:{speaker}] [laughing] {text}"
    elif any(w in lower_text for w in ["sighed", "exhausted", "tired", "resigned"]):
        tagged = f"[SPEAKER:{speaker}] [sighing] {text}"
    elif any(w in lower_text for w in ["excited", "thrilled", "eager", "couldn't wait"]):
        tagged = f"[SPEAKER:{speaker}] [excited] {text}"

    return tagged


def _parse_tagged_response(response: str, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse LLM response and merge tags back into paragraph data."""
    # Try to extract tagged paragraphs by index markers
    result = []
    for para in paragraphs:
        idx = para.get("index", 0)
        # Look for the paragraph in the response
        pattern = re.compile(
            rf"\[{idx}\]\s*(.*?)(?=\[\d+\]|\Z)",
            re.DOTALL,
        )
        match = pattern.search(response)
        if match:
            tagged_text = match.group(1).strip()
            # Extract tags from the text
            tags = re.findall(r"\[([\w:]+)(?::([^\]]+))?\]", tagged_text)
            tag_list = []
            for tag_name, tag_value in tags:
                if tag_name in ("SPEAKER",):
                    continue
                if tag_value:
                    tag_list.append(f"{tag_name}:{tag_value}")
                else:
                    tag_list.append(tag_name)
            result.append({
                **para,
                "text": tagged_text,
                "prosody_tags": tag_list,
            })
        else:
            # Fallback: apply rule-based tags
            tagged = _apply_rule_based_tags(para)
            result.append({
                **para,
                "text": tagged,
                "prosody_tags": [],
                "tag_source": "rule_based",
            })
    return result


class ProsodyPlanner(BaseAgent):
    """LLM-powered prosody and emotion planning engine."""

    name = "prosody_planner"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        chapters = input_data.get("chapters", [])
        if not chapters:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                error="No chapters in input",
            )

        planned_chapters = []
        total_cost = 0.0
        total_chars_in = 0
        total_chars_out = 0

        for chapter in chapters:
            planned_scenes = []
            chapter_title = chapter.get("title", "")

            for scene in chapter.get("scenes", []):
                paragraphs = scene.get("paragraphs", [])
                if not paragraphs:
                    planned_scenes.append(scene)
                    continue

                # Group paragraphs by speaker for batch processing
                # Process in batches of 10 to stay within context limits
                batch_size = 10
                planned_paragraphs = []

                for i in range(0, len(paragraphs), batch_size):
                    batch = paragraphs[i:i + batch_size]
                    para_text = "\n".join(
                        f"[{p['index']}] {p['text'][:300]}"
                        for p in batch
                    )
                    total_chars_in += len(para_text)

                    # Get dominant speaker for context
                    speakers = [p.get("speaker", "narrator") for p in batch]
                    dominant_speaker = max(set(speakers), key=speakers.count)

                    prompt = USER_PROMPT_TEMPLATE.format(
                        speaker=dominant_speaker,
                        context=f"Chapter: {chapter_title}",
                        paragraphs=para_text,
                    )

                    response = _call_ollama(prompt, AGENT4_MODEL)
                    if response is None:
                        response = _call_ollama(prompt, AGENT4_FALLBACK_MODEL)

                    if response:
                        tagged = _parse_tagged_response(response, batch)
                        planned_paragraphs.extend(tagged)
                        total_cost += _estimate_cost(para_text)
                    else:
                        # Full fallback: rule-based tags
                        for p in batch:
                            tagged = _apply_rule_based_tags(p)
                            planned_paragraphs.append({
                                **p,
                                "text": tagged,
                                "prosody_tags": [],
                                "tag_source": "rule_based",
                            })

                    total_chars_out += sum(len(p.get("text", "")) for p in planned_paragraphs[-len(batch):])

                planned_scenes.append({
                    **scene,
                    "paragraphs": planned_paragraphs,
                })

            planned_chapters.append({
                **chapter,
                "scenes": planned_scenes,
            })

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={"chapters": planned_chapters},
            cost_usd=total_cost,
            characters_in=total_chars_in,
            characters_out=total_chars_out,
        )
