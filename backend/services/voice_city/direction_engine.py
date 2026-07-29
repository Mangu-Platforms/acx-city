"""Automatic dialogue analysis and bounded production-direction plans.

The detector is intentionally deterministic and explainable.  It recognizes
quoted dialogue and screenplay-style ``CHARACTER: line`` turns, attributes a
speaker only when nearby text provides evidence, and leaves uncertain dialogue
on the narrator rather than guessing.  Direction plans may change performance
but never rewrite a saved speaker's immutable identity controls.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from .generator import parameters_from_description
from .parameter_schema import CONTROL_BY_PATH, default_parameters, get_path, normalize_parameters


class DirectionError(ValueError):
    pass


_SPEECH_VERBS = (
    "said|asked|replied|answered|whispered|shouted|called|murmured|cried|"
    "exclaimed|added|continued|observed|remarked|insisted|warned|promised|"
    "laughed|sighed|snapped|yelled|announced|explained|admitted|agreed"
)
_NAME = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,2}"
_BEFORE_ATTRIBUTION = re.compile(rf"(?P<name>{_NAME})\s+(?:{_SPEECH_VERBS})\s*[,;:]?\s*$")
_AFTER_ATTRIBUTION = re.compile(rf"^\s*[,;:]?\s*(?P<name>{_NAME})\s+(?:{_SPEECH_VERBS})\b")
_AFTER_INVERTED = re.compile(rf"^\s*[,;:]?\s*(?:{_SPEECH_VERBS})\s+(?P<name>{_NAME})\b")
_STAGE_LINE = re.compile(rf"^\s*(?P<name>{_NAME})\s*:\s*(?P<body>.+?)\s*$")
_QUOTE = re.compile(r"[\"“](?P<body>.+?)[\"”]", re.DOTALL)
_SCENE_BREAK = re.compile(r"^\s*(?:\*{3,}|#{3,}|—{3,}|-{3,}|scene\s+\d+|scene\s+break)\s*$", re.IGNORECASE)
_SENTENCE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)", re.DOTALL)
_PRONOUNS = {"i", "he", "she", "they", "we", "you", "it", "someone", "everyone"}
_DIRECTION_PREFIXES = (
    "performance.", "emotion.", "timing.", "narration.", "pitch.",
    "articulation.", "breath_texture.", "environment.", "post.", "interpretation.",
)


def normalize_character_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\w'’\-]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _credible_name(value: str | None) -> str | None:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:\t\n\r")
    if not name or normalize_character_name(name) in _PRONOUNS:
        return None
    return name


def _infer_speaker(before: str, after: str) -> tuple[str | None, float, str | None]:
    before_match = _BEFORE_ATTRIBUTION.search(before[-180:])
    if before_match:
        name = _credible_name(before_match.group("name"))
        if name:
            return name, 0.98, "preceding-attribution"
    for pattern, evidence in ((_AFTER_ATTRIBUTION, "following-attribution"), (_AFTER_INVERTED, "following-inverted-attribution")):
        match = pattern.search(after[:180])
        if match:
            name = _credible_name(match.group("name"))
            if name:
                return name, 0.98, evidence
    return None, 0.0, None


def _sentence_parts(text: str) -> list[str]:
    if not text:
        return []
    parts = [match.group(0) for match in _SENTENCE.finditer(text) if match.group(0).strip()]
    return parts or [text]


def detect_dialogue_segments(text: str) -> list[dict[str, Any]]:
    """Return ordered narration/dialogue segments with evidence-backed speakers."""
    source = str(text or "")
    if not source.strip():
        return []

    raw: list[dict[str, Any]] = []
    offset = 0
    scene_index = 0
    for line in source.splitlines(keepends=True):
        line_without_break = line.rstrip("\r\n")
        if _SCENE_BREAK.match(line_without_break):
            if line:
                raw.append({"kind": "narration", "speaker": None, "text": line, "start": offset, "end": offset + len(line), "scene_index": scene_index, "confidence": 1.0, "evidence": "scene-break"})
            scene_index += 1
            offset += len(line)
            continue

        stage = _STAGE_LINE.match(line_without_break)
        if stage:
            body_start = line.find(stage.group("body"))
            prefix = line[:body_start]
            if prefix:
                raw.append({"kind": "narration", "speaker": None, "text": prefix, "start": offset, "end": offset + body_start, "scene_index": scene_index, "confidence": 1.0, "evidence": "stage-label"})
            raw.append({"kind": "dialogue", "speaker": _credible_name(stage.group("name")), "text": line[body_start:], "start": offset + body_start, "end": offset + len(line), "scene_index": scene_index, "confidence": 0.99, "evidence": "screenplay-label"})
            offset += len(line)
            continue

        cursor = 0
        matches = list(_QUOTE.finditer(line))
        if not matches:
            raw.append({"kind": "narration", "speaker": None, "text": line, "start": offset, "end": offset + len(line), "scene_index": scene_index, "confidence": 1.0, "evidence": None})
            offset += len(line)
            continue
        for match in matches:
            if match.start() > cursor:
                raw.append({"kind": "narration", "speaker": None, "text": line[cursor:match.start()], "start": offset + cursor, "end": offset + match.start(), "scene_index": scene_index, "confidence": 1.0, "evidence": None})
            speaker, confidence, evidence = _infer_speaker(line[:match.start()], line[match.end():])
            raw.append({"kind": "dialogue", "speaker": speaker, "text": match.group(0), "start": offset + match.start(), "end": offset + match.end(), "scene_index": scene_index, "confidence": confidence, "evidence": evidence})
            cursor = match.end()
        if cursor < len(line):
            raw.append({"kind": "narration", "speaker": None, "text": line[cursor:], "start": offset + cursor, "end": offset + len(line), "scene_index": scene_index, "confidence": 1.0, "evidence": None})
        offset += len(line)

    segments: list[dict[str, Any]] = []
    sentence_index = 0
    for item in raw:
        local_cursor = item["start"]
        for part in _sentence_parts(item["text"]):
            length = len(part)
            if not part.strip():
                local_cursor += length
                continue
            segments.append({
                "index": len(segments),
                "sentence_index": sentence_index,
                "scene_index": item["scene_index"],
                "kind": item["kind"],
                "speaker": item["speaker"],
                "text": part,
                "start": local_cursor,
                "end": local_cursor + length,
                "confidence": item["confidence"],
                "evidence": item["evidence"],
            })
            sentence_index += 1
            local_cursor += length
    return segments


def analyze_dialogue(text: str, *, max_segments: int = 4000) -> dict[str, Any]:
    if len(str(text or "")) > 2_000_000:
        raise DirectionError("Dialogue analysis accepts at most 2,000,000 characters")
    segments = detect_dialogue_segments(text)
    if len(segments) > max_segments:
        segments = segments[:max_segments]
    counts: Counter[str] = Counter()
    excerpts: dict[str, list[str]] = defaultdict(list)
    uncertain = 0
    dialogue_count = 0
    for segment in segments:
        if segment["kind"] != "dialogue":
            continue
        dialogue_count += 1
        if segment["speaker"]:
            key = str(segment["speaker"])
            counts[key] += 1
            if len(excerpts[key]) < 3:
                excerpts[key].append(segment["text"].strip()[:240])
        else:
            uncertain += 1
    speakers = [
        {"name": name, "normalized_name": normalize_character_name(name), "turns": count, "excerpts": excerpts[name]}
        for name, count in counts.most_common()
    ]
    return {
        "character_count": len(str(text or "")),
        "segment_count": len(segments),
        "dialogue_segment_count": dialogue_count,
        "unattributed_dialogue_count": uncertain,
        "scene_count": 1 + max((int(segment["scene_index"]) for segment in segments), default=0),
        "speakers": speakers,
        "segments": segments,
        "detector": "voice-city-dialogue-v1",
        "policy": "Only evidence-backed speaker attributions are cast; uncertain dialogue remains with the narrator.",
    }


def _flatten(value: Mapping[str, Any], prefix: str = ""):
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            yield from _flatten(item, path)
        else:
            yield path, item


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    cursor = document
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def validate_direction_patch(patch: Mapping[str, Any] | None) -> dict[str, Any]:
    sparse = dict(patch or {})
    if not sparse:
        return {}
    flattened = list(_flatten(sparse))
    if len(flattened) > 120:
        raise DirectionError("A direction patch may change at most 120 controls")
    for path, _value in flattened:
        if path not in CONTROL_BY_PATH:
            raise DirectionError(f"Unknown direction control: {path}")
        if not path.startswith(_DIRECTION_PREFIXES):
            raise DirectionError(f"Direction may not change immutable speaker identity control: {path}")
    canonical, _warnings = normalize_parameters(sparse)
    result: dict[str, Any] = {}
    for path, _value in flattened:
        _set_path(result, path, copy.deepcopy(get_path(canonical, path)))
    return result


def performance_patch_from_instructions(instructions: str, *, seed: int = 481928) -> dict[str, Any]:
    text = str(instructions or "").strip()
    if not text:
        return {}
    described, _warnings = parameters_from_description(text, seed=seed)
    baseline = default_parameters(seed)
    patch: dict[str, Any] = {}
    for path, control in CONTROL_BY_PATH.items():
        if not path.startswith(_DIRECTION_PREFIXES):
            continue
        value = get_path(described, path)
        if value != get_path(baseline, path):
            _set_path(patch, path, copy.deepcopy(value))
    return validate_direction_patch(patch)


def _style_value(value: Any, *, seed: int) -> dict[str, Any]:
    if isinstance(value, str):
        return performance_patch_from_instructions(value, seed=seed)
    if isinstance(value, Mapping):
        return validate_direction_patch(value)
    raise DirectionError("Chapter/scene style values must be text instructions or parameter patches")


def validate_direction_plan(plan: Mapping[str, Any] | None, *, seed: int = 481928) -> dict[str, Any]:
    incoming = dict(plan or {})
    instructions = str(incoming.get("director_instructions") or "").strip()
    if len(instructions) > 4000:
        raise DirectionError("director_instructions must be 4,000 characters or fewer")
    cast_input = incoming.get("cast") or []
    if not isinstance(cast_input, Sequence) or isinstance(cast_input, (str, bytes)):
        raise DirectionError("cast must be a list")
    if len(cast_input) > 100:
        raise DirectionError("A production may cast at most 100 characters")
    cast: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in cast_input:
        if not isinstance(item, Mapping):
            raise DirectionError("Each cast entry must be an object")
        name = str(item.get("character_name") or item.get("name") or "").strip()
        normalized = normalize_character_name(name)
        if not normalized or len(name) > 200:
            raise DirectionError("Each cast entry requires a character_name of 200 characters or fewer")
        if normalized in seen:
            raise DirectionError(f"Duplicate character cast entry: {name}")
        seen.add(normalized)
        aliases = []
        for alias in item.get("aliases") or []:
            clean = str(alias).strip()
            if clean and len(clean) <= 200 and normalize_character_name(clean) not in {normalized, *(normalize_character_name(value) for value in aliases)}:
                aliases.append(clean)
        if len(aliases) > 20:
            raise DirectionError(f"{name} has more than 20 aliases")
        version_id = str(item.get("voice_version_id") or "").strip()
        if not version_id:
            raise DirectionError(f"{name} requires voice_version_id")
        cast.append({
            "character_name": name,
            "normalized_name": normalized,
            "aliases": aliases,
            "voice_version_id": version_id,
            "style_overrides": validate_direction_patch(item.get("style_overrides") or {}),
        })

    chapter_styles_input = incoming.get("chapter_styles") or {}
    scene_styles_input = incoming.get("scene_styles") or {}
    if not isinstance(chapter_styles_input, Mapping) or not isinstance(scene_styles_input, Mapping):
        raise DirectionError("chapter_styles and scene_styles must be objects")
    if len(chapter_styles_input) > 500 or len(scene_styles_input) > 2000:
        raise DirectionError("Direction plan contains too many chapter or scene styles")
    chapter_styles = {str(key)[:300]: _style_value(value, seed=seed) for key, value in chapter_styles_input.items()}
    scene_styles = {str(key)[:300]: _style_value(value, seed=seed) for key, value in scene_styles_input.items()}
    explicit_director_patch = validate_direction_patch(incoming.get("director_parameter_patch") or {})
    generated_director_patch = performance_patch_from_instructions(instructions, seed=seed)
    director_patch = copy.deepcopy(generated_director_patch)
    for path, value in _flatten(explicit_director_patch):
        _set_path(director_patch, path, value)

    policy = str(incoming.get("unknown_dialogue_policy") or "narrator")
    if policy not in {"narrator", "skip"}:
        raise DirectionError("unknown_dialogue_policy must be narrator or skip")
    return {
        "enabled": bool(incoming.get("enabled", True)),
        "automatic_dialogue_detection": bool(incoming.get("automatic_dialogue_detection", True)),
        "unknown_dialogue_policy": policy,
        "director_instructions": instructions,
        "director_parameter_patch": director_patch,
        "default_dialogue_overrides": validate_direction_patch(incoming.get("default_dialogue_overrides") or {"narration": {"dialogue_lift": 0.2}}),
        "chapter_styles": chapter_styles,
        "scene_styles": scene_styles,
        "cast": cast,
        "detector_version": "voice-city-dialogue-v1",
    }
