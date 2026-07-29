"""Built-in Voice City presets.

These are curated, provider-agnostic starting points for common audiobook
jobs.  Each preset is authored as a sparse patch of schema control paths and
converted to a full canonical document through
``parameter_schema.normalize_parameters`` at import time, so the shipped
``parameters`` payloads are guaranteed to round-trip the schema unchanged and
carry no clamp/constraint warnings.  Ids use the ``system:`` namespace, which
the service layer treats as read-only (built-ins cannot be deleted and shadow
no database rows).  Serialized shape mirrors the service's custom-preset
serialization so the frontend can render both lists interchangeably.

Everything here is static data plus pure schema calls: no I/O, no clock, no
randomness.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .parameter_schema import CONTROL_BY_PATH, normalize_parameters, set_parameter_value

#: Slider defaults outside their own declared range (the schema ships
#: ``source.creak`` at -0.15 on a 0..1 scale).  Presets pin these to their
#: clamped canonical values so every shipped document is a warning-free
#: fixed point of ``normalize_parameters``.
_RANGE_PINNED_DEFAULTS: dict[str, float] = {
    control.path: round(max(float(control.minimum), min(float(control.maximum), float(control.default))), 6)
    for control in CONTROL_BY_PATH.values()
    if control.control_type == "slider"
    and control.minimum is not None
    and control.maximum is not None
    and not float(control.minimum) <= float(control.default) <= float(control.maximum)
}


def _document(seed: int, values: Mapping[str, Any]) -> dict[str, Any]:
    """Build a nested sparse parameter patch from flat ``path: value`` pairs.

    ``set_parameter_value`` validates every path against the schema, so a
    typo in this file fails loudly at import instead of surfacing as a broken
    preset in the client.
    """
    document: dict[str, Any] = {"seed": int(seed)}
    for path, value in values.items():
        set_parameter_value(document, path, value)
    for path, pinned in _RANGE_PINNED_DEFAULTS.items():
        if path not in values:
            set_parameter_value(document, path, pinned)
    return document


_PRESET_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "system:warm-fiction-narrator",
        "name": "Warm Fiction Narrator",
        "description": "A warm, easy storyteller for general fiction: relaxed pacing, gentle melody, and light dialogue lift.",
        "category": "fiction",
        "parameters": _document(611001, {
            "identity.warmth": 0.45,
            "identity.timbre_complexity": 0.3,
            "texture.velvet": 0.3,
            "performance.conversationality": 0.5,
            "performance.expressiveness": 0.35,
            "performance.energy": 0.15,
            "performance.intimacy": 0.3,
            "pitch.melodic_variation": 0.35,
            "narration.fiction_immersion": 0.45,
            "narration.dialogue_lift": 0.3,
            "emotion.empathy": 0.25,
            "environment.mic_distance": 0.2,
        }),
    },
    {
        "id": "system:classic-british-storyteller",
        "name": "Classic British Storyteller",
        "description": "Measured Received Pronunciation with a settled, mature delivery for classic and literary fiction.",
        "category": "fiction",
        "parameters": _document(611002, {
            "accent.locale": "en-GB",
            "accent.region": "received-pronunciation",
            "accent.strength": 0.45,
            "accent.rhoticity": 0.15,
            "accent.formality": 0.35,
            "identity.perceived_age": 0.35,
            "identity.pitch_center": -0.15,
            "identity.warmth": 0.35,
            "identity.articulation": 0.35,
            "articulation.consonant_sharpness": 0.25,
            "pitch.phrase_arc": 0.25,
            "timing.pause_duration": 0.3,
            "performance.speaking_rate": 0.96,
            "narration.fiction_immersion": 0.35,
            "emotion.solemnity": 0.1,
        }),
    },
    {
        "id": "system:crisp-nonfiction-guide",
        "name": "Crisp Nonfiction Guide",
        "description": "Bright, precise, and confident: a clear explainer voice for general nonfiction and business titles.",
        "category": "nonfiction",
        "parameters": _document(611003, {
            "identity.articulation": 0.4,
            "articulation.consonant_sharpness": 0.3,
            "articulation.vowel_definition": 0.25,
            "identity.brightness": 0.2,
            "identity.presence": 0.25,
            "performance.confidence": 0.35,
            "performance.authority": 0.3,
            "performance.speaking_rate": 1.05,
            "timing.pause_density": 0.3,
            "narration.nonfiction_objectivity": 0.5,
            "narration.technical_precision": 0.45,
            "interpretation.punctuation_sensitivity": 0.7,
        }),
    },
    {
        "id": "system:intimate-memoir",
        "name": "Intimate Memoir",
        "description": "Close-microphone, confiding delivery with restrained emotion for memoir and personal essay.",
        "category": "memoir",
        "parameters": _document(611004, {
            "performance.intimacy": 0.5,
            "narration.memoir_intimacy": 0.5,
            "narration.internal_monologue": 0.4,
            "identity.texture.breathiness": 0.18,
            "identity.warmth": 0.4,
            "performance.energy": -0.1,
            "performance.conversationality": 0.45,
            "performance.restraint": 0.5,
            "emotion.tenderness": 0.2,
            "environment.mic_distance": 0.1,
            "environment.proximity_effect": 0.25,
            "environment.listener_distance": 0.05,
        }),
    },
    {
        "id": "system:epic-fantasy-bard",
        "name": "Epic Fantasy Bard",
        "description": "Theatrical range and broad melody for high fantasy: big scenes land, quiet scenes breathe.",
        "category": "fiction",
        "parameters": _document(611005, {
            "performance.theatricality": 0.4,
            "performance.expressiveness": 0.5,
            "narration.dynamic_range": 0.55,
            "identity.pitch_range": 0.5,
            "pitch.melodic_variation": 0.45,
            "pitch.emphasis_excursion": 0.4,
            "identity.body_size": 0.3,
            "resonance.low_body": 0.3,
            "performance.suspense": 0.25,
            "narration.suspense_pacing": 0.3,
            "narration.fiction_immersion": 0.5,
            "narration.dialogue_characterization": 0.35,
        }),
    },
    {
        "id": "system:bright-childrens-storyteller",
        "name": "Bright Children's Storyteller",
        "description": "Friendly, energetic, and extra-clear pacing for children's books and middle-grade fiction.",
        "category": "children",
        "parameters": _document(611006, {
            "narration.children_storytelling": 0.6,
            "performance.friendliness": 0.5,
            "performance.energy": 0.35,
            "performance.expressiveness": 0.5,
            "emotion.joy": 0.3,
            "emotion.curiosity": 0.3,
            "identity.pitch_center": 0.2,
            "identity.pitch_range": 0.45,
            "identity.warmth": 0.35,
            "identity.articulation": 0.3,
            "performance.speaking_rate": 0.98,
            "timing.pause_duration": 0.25,
        }),
    },
    {
        "id": "system:midnight-thriller",
        "name": "Midnight Thriller Narrator",
        "description": "Low, dry, and controlled with held-breath pacing for thrillers, noir, and dark mysteries.",
        "category": "thriller",
        "parameters": _document(611007, {
            "identity.pitch_center": -0.3,
            "identity.brightness": -0.25,
            "identity.texture.gravel": 0.18,
            "texture.smokiness": 0.2,
            "texture.dryness": 0.2,
            "performance.suspense": 0.4,
            "narration.suspense_pacing": 0.45,
            "narration.dynamic_range": 0.45,
            "performance.restraint": 0.55,
            "performance.energy": -0.05,
            "performance.intimacy": 0.25,
            "timing.pause_duration": 0.35,
        }),
    },
    {
        "id": "system:technical-manual",
        "name": "Technical Manual Reader",
        "description": "Deliberate pace, tight tempo stability, and careful term handling for technical and reference material.",
        "category": "technical",
        "parameters": _document(611008, {
            "narration.technical_precision": 0.6,
            "articulation.technical_term_care": 0.75,
            "identity.articulation": 0.45,
            "performance.speaking_rate": 0.94,
            "timing.pause_density": 0.35,
            "timing.tempo_stability": 0.8,
            "narration.nonfiction_objectivity": 0.55,
            "interpretation.semantic_emphasis": 0.45,
            "interpretation.math_expression_care": 0.75,
            "interpretation.code_expression_care": 0.75,
            "performance.expressiveness": 0.15,
            "pitch.melodic_variation": 0.15,
        }),
    },
    {
        "id": "system:soothing-meditation",
        "name": "Soothing Meditation Guide",
        "description": "Slow, close, and very calm with audible breath for meditation, sleep stories, and wellness titles.",
        "category": "wellness",
        "parameters": _document(611009, {
            "emotion.calm": 0.55,
            "emotion.reassurance": 0.4,
            "performance.energy": -0.35,
            "performance.speaking_rate": 0.82,
            "performance.intimacy": 0.45,
            "identity.warmth": 0.45,
            "identity.texture.breathiness": 0.22,
            "breath.audibility": 0.2,
            "timing.pause_duration": 0.5,
            "timing.pause_density": 0.45,
            "pitch.contour_smoothness": 0.75,
            "environment.mic_distance": 0.12,
            "environment.proximity_effect": 0.3,
        }),
    },
    {
        "id": "system:broadcast-brief",
        "name": "Broadcast News Brief",
        "description": "Forward, authoritative, and quick: a newsroom read for summaries, journalism, and current affairs.",
        "category": "broadcast",
        "parameters": _document(611010, {
            "performance.authority": 0.45,
            "performance.confidence": 0.45,
            "identity.articulation": 0.45,
            "articulation.consonant_sharpness": 0.35,
            "performance.speaking_rate": 1.12,
            "accent.formality": 0.4,
            "identity.presence": 0.35,
            "resonance.forward_placement": 0.3,
            "performance.energy": 0.25,
            "narration.nonfiction_objectivity": 0.5,
            "narration.emphasis_strength": 0.35,
            "environment.microphone_model": "broadcast-dynamic",
        }),
    },
)


def _build_presets() -> tuple[dict[str, Any], ...]:
    built: list[dict[str, Any]] = []
    for source in _PRESET_SOURCES:
        preset_id = str(source["id"])
        if not preset_id.startswith("system:"):
            raise RuntimeError(f"Built-in preset id {preset_id!r} must use the system: namespace")
        canonical, warnings = normalize_parameters(source["parameters"])
        if warnings:
            raise RuntimeError(
                f"Built-in preset {preset_id!r} does not normalize cleanly: {warnings}"
            )
        recheck, recheck_warnings = normalize_parameters(canonical)
        if recheck != canonical or recheck_warnings:
            raise RuntimeError(
                f"Built-in preset {preset_id!r} is not a stable fixed point of normalize_parameters"
            )
        built.append(
            {
                "id": preset_id,
                "name": str(source["name"]),
                "description": str(source["description"]),
                "category": str(source["category"]),
                "is_template": True,
                "parameters": canonical,
                "source_voice_version_id": None,
                "created_at": None,
                "updated_at": None,
            }
        )
    return tuple(built)


_BUILT_IN_PRESETS = _build_presets()
_PRESETS_BY_ID = {preset["id"]: preset for preset in _BUILT_IN_PRESETS}


def built_in_presets() -> list[dict[str, Any]]:
    """Return every built-in preset as an independent copy.

    Copies keep callers from mutating the shared module-level documents that
    back ``get_built_in_preset`` lookups.
    """
    return [copy.deepcopy(preset) for preset in _BUILT_IN_PRESETS]


def get_built_in_preset(preset_id: str) -> dict[str, Any] | None:
    """Look up one built-in preset by id; None for unknown or custom ids."""
    preset = _PRESETS_BY_ID.get(str(preset_id or ""))
    return copy.deepcopy(preset) if preset is not None else None
