"""Prosody Tag Parser — interprets Agent 4's emotion/prosody tags for synthesis.

The synthesis worker calls this module to convert tagged text into an ordered
segment list that the TTS engine can process.

Tag vocabulary:
    [angry] [sad] [whisper] [soft] [breathy] [excited] [embarrassed]
    [laughing] [sobbing] [sighing] [pause:NNN] [scene_break:3000]
    [rate:slow] [rate:fast] [emphasis] [SPEAKER:Name]
    [pron:PHONETIC]word[/pron]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Segment:
    """A single synthesis segment with prosody metadata."""
    type: str  # "text" | "pause" | "scene_break" | "speaker_change"
    content: str = ""
    speaker: str = "narrator"
    emotion: str | None = None
    rate: float = 1.0  # 1.0 = normal, 0.8 = slow, 1.2 = fast
    pause_ms: int = 0
    emphasis: bool = False
    tags: list[str] = field(default_factory=list)
    pronunciation_hints: dict[str, str] = field(default_factory=dict)


# Tag pattern
TAG_PATTERN = re.compile(r"\[(\w+)(?::([^\]]+))?\]")
PRON_PATTERN = re.compile(r"\[pron:([^\]]+)\](.*?)\[/pron\]")


def parse_tagged_text(text: str, current_speaker: str = "narrator") -> list[Segment]:
    """Parse prosody-tagged text into an ordered segment list.

    Args:
        text: Text with inline prosody tags from Agent 4
        current_speaker: Default speaker if no [SPEAKER:] tag

    Returns:
        Ordered list of Segment objects for the synthesis engine
    """
    segments: list[Segment] = []
    current_segment_text: list[str] = []
    active_emotion: str | None = None
    active_rate: float = 1.0
    active_tags: list[str] = []
    speaker = current_speaker
    emphasis_next = False
    pronunciation_hints: dict[str, str] = {}

    def flush_text():
        """Flush accumulated text into a segment."""
        text_content = "".join(current_segment_text).strip()
        if text_content:
            # Clean up pronunciation hints
            clean_text = PRON_PATTERN.sub(r"\2", text_content)
            segments.append(Segment(
                type="text",
                content=clean_text,
                speaker=speaker,
                emotion=active_emotion,
                rate=active_rate,
                emphasis=emphasis_next,
                tags=list(active_tags),
                pronunciation_hints=dict(pronunciation_hints),
            ))
        current_segment_text.clear()

    # Process pronunciation hints first
    for match in PRON_PATTERN.finditer(text):
        phonetic = match.group(1)
        word = match.group(2)
        pronunciation_hints[word] = phonetic

    # Remove pron tags for main parsing
    clean_text = PRON_PATTERN.sub(r"\2", text)

    # Tokenize by tags
    pos = 0
    for match in TAG_PATTERN.finditer(clean_text):
        # Add text before this tag
        before = clean_text[pos:match.start()]
        if before:
            current_segment_text.append(before)

        tag_name = match.group(1)
        tag_value = match.group(2)

        if tag_name == "SPEAKER" and tag_value:
            flush_text()
            speaker = tag_value
            segments.append(Segment(
                type="speaker_change",
                speaker=speaker,
            ))
            active_emotion = None
            active_rate = 1.0
            active_tags.clear()

        elif tag_name == "pause" and tag_value:
            flush_text()
            try:
                ms = int(tag_value)
                segments.append(Segment(
                    type="pause",
                    pause_ms=max(0, min(ms, 10000)),
                ))
            except ValueError:
                pass

        elif tag_name == "scene_break" and tag_value:
            flush_text()
            try:
                ms = int(tag_value)
            except ValueError:
                ms = 3000
            segments.append(Segment(
                type="scene_break",
                pause_ms=max(0, min(ms, 10000)),
            ))

        elif tag_name == "rate" and tag_value:
            flush_text()
            if tag_value == "slow":
                active_rate = 0.8
            elif tag_value == "fast":
                active_rate = 1.2
            else:
                try:
                    active_rate = float(tag_value)
                except ValueError:
                    active_rate = 1.0
            active_tags.append(f"rate:{tag_value}")

        elif tag_name == "emphasis":
            emphasis_next = True

        elif tag_name in ("angry", "sad", "whisper", "soft", "breathy",
                          "excited", "embarrassed", "laughing", "sobbing", "sighing"):
            flush_text()
            active_emotion = tag_name
            active_tags.append(tag_name)

        else:
            # Unknown tag — treat as text
            current_segment_text.append(f"[{tag_name}" + (f":{tag_value}" if tag_value else "") + "]")

        pos = match.end()

    # Remaining text
    remaining = clean_text[pos:]
    if remaining:
        current_segment_text.append(remaining)

    flush_text()

    # Merge consecutive text segments with the same speaker/emotion
    merged: list[Segment] = []
    for seg in segments:
        if (merged and
            seg.type == "text" and
            merged[-1].type == "text" and
            seg.speaker == merged[-1].speaker and
            seg.emotion == merged[-1].emotion and
            seg.rate == merged[-1].rate and
            not seg.emphasis and not merged[-1].emphasis):
            merged[-1].content += " " + seg.content
            merged[-1].pronunciation_hints.update(seg.pronunciation_hints)
        else:
            merged.append(seg)

    return merged


def segments_to_plain_text(segments: list[Segment]) -> str:
    """Convert segments back to plain text (for caching/content hashing)."""
    parts = []
    for seg in segments:
        if seg.type == "text":
            parts.append(seg.content)
        elif seg.type == "pause":
            parts.append(f"[pause:{seg.pause_ms}]")
        elif seg.type == "scene_break":
            parts.append(f"[scene_break:{seg.pause_ms}]")
        elif seg.type == "speaker_change":
            parts.append(f"[SPEAKER:{seg.speaker}]")
    return "\n".join(parts)


def extract_emotion_conditioning(emotion: str | None) -> dict[str, Any]:
    """Convert emotion tag to model-specific conditioning parameters.

    Returns a dict of parameters that can be passed to TTS models like
    Kokoro-82M or Fish Speech.
    """
    if not emotion:
        return {}

    emotion_map = {
        "angry": {
            "pitch_shift": 1.2,
            "speed_factor": 1.15,
            "energy": 1.3,
            "description": "raised pitch, faster rate, harder consonants",
        },
        "sad": {
            "pitch_shift": 0.85,
            "speed_factor": 0.85,
            "energy": 0.7,
            "description": "lower pitch, slower rate, softer delivery",
        },
        "whisper": {
            "pitch_shift": 0.95,
            "speed_factor": 0.9,
            "energy": 0.4,
            "description": "reduced amplitude, breathy, intimate",
        },
        "soft": {
            "pitch_shift": 1.0,
            "speed_factor": 0.95,
            "energy": 0.6,
            "description": "gentle volume, warm tone",
        },
        "breathy": {
            "pitch_shift": 1.05,
            "speed_factor": 0.9,
            "energy": 0.5,
            "description": "airy voice quality",
        },
        "excited": {
            "pitch_shift": 1.15,
            "speed_factor": 1.2,
            "energy": 1.4,
            "description": "faster rate, higher energy",
        },
        "embarrassed": {
            "pitch_shift": 0.95,
            "speed_factor": 0.9,
            "energy": 0.7,
            "description": "slightly slower, halting quality",
        },
        "laughing": {
            "pitch_shift": 1.1,
            "speed_factor": 1.1,
            "energy": 1.2,
            "description": "bright tone",
        },
        "sobbing": {
            "pitch_shift": 0.8,
            "speed_factor": 0.7,
            "energy": 0.6,
            "description": "interrupted delivery, catch in voice",
        },
        "sighing": {
            "pitch_shift": 0.9,
            "speed_factor": 0.85,
            "energy": 0.5,
            "description": "exhale quality",
        },
    }

    return emotion_map.get(emotion, {})
