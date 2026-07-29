"""Safety, ownership, provenance, and similarity gates for Voice City."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .parameter_schema import canonical_fingerprint, get_path


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    classification: str
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification,
            "reasons": list(self.reasons),
            "evidence": self.evidence,
        }


# Verb forms are matched with optional -s/-ed/-ing suffixes (a bare "sound"
# does not match "sounds" under \b...\b, which is exactly how the original
# version of this list was bypassed by simple pluralization).
_VOICE_VERB = r"(?:voice|sound|speak|talk|narrate)(?:s|ed|ing)?"

_IMPERSONATION_PATTERNS = [
    re.compile(r"\b(?:clone|copy|duplicate|recreate|impersonat\w*|imitat\w*|mimic\w*)\b.{0,40}\b(?:voice|speaker|narrator|person)\b", re.I),
    re.compile(rf"\b{_VOICE_VERB}\s+(?:exactly\s+)?(?:like|as)\b", re.I),
    re.compile(r"\b(?:the\s+)?voice\s+of\b", re.I),
    re.compile(r"\bcelebrity\s+voice\b", re.I),
    re.compile(r"\bdeepfake\b", re.I),
    re.compile(r"\b(?:impression|impersonation)s?\s+of\b", re.I),
    re.compile(r"\bdo(?:es|ing)?\s+an?\b.{0,20}\bimpression\b", re.I),
    re.compile(r"\bin\s+the\s+(?:style|voice)\s+of\b", re.I),
    # Indirect person references that name no verb at all: "the guy from...",
    # "the actor who played...", "the narrator behind...".
    re.compile(r"\bthe\s+(?:guy|girl|man|woman|person|actor|actress|narrator|voice\s*actor|character|dude)\s+(?:from|who|that|behind|in)\b", re.I),
]

# Descriptions are allowed to use physical/performance characteristics.  These
# phrases are blocked because they request identity imitation rather than a
# synthetic characteristic recipe.
_IDENTITY_INTENT_TERMS = {
    "exact voice",
    "indistinguishable from",
    "pass as",
    "fool listeners",
    "without consent",
    "unauthorized voice",
}

# Trivial digit/symbol-for-letter evasions ("s0unds l1ke") are undone before
# any keyword match runs. This is a heuristic first line of defense, not a
# complete evasion-proof classifier -- letter-spaced evasion ("s o u n d s")
# is a known residual gap, which is part of why the proper-noun heuristic
# below and the render-time safety checks exist as additional layers.
_LEET_TRANSLATION = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
})


def _normalize_for_screening(text: str) -> str:
    return text.lower().translate(_LEET_TRANSLATION)


# A synthetic voice is described by acoustic characteristics (age, pitch,
# warmth, accent strength...) -- it never needs to *name* a real person. So a
# capitalized, name-shaped phrase (two or three Title-Case words) appearing
# near voice/performance vocabulary is treated as a likely named-person
# request and blocked by default, rather than trying to maintain a celebrity
# name list (which can never be complete). The stoplist below keeps ordinary
# Title-Case descriptions ("Warm British Narrator") from being misread as a
# name; anything not entirely made of these common description words is
# treated as name-shaped.
_DESCRIPTIVE_WORDS = {
    "warm", "deep", "young", "old", "older", "middle", "aged", "male", "female",
    "british", "american", "australian", "irish", "scottish", "southern",
    "narrator", "narration", "voice", "character", "performance", "style",
    "gravelly", "smooth", "husky", "bright", "soft", "gentle", "strong",
    "storyteller", "announcer", "the", "a", "an", "with", "and", "slow",
    "fast", "calm", "energetic", "serious", "playful", "formal", "casual",
    "confident", "soothing", "raspy", "clear", "rich", "light", "heavy",
    "friendly", "authoritative", "mature", "youthful", "narrator's",
}
_PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
_POSSESSIVE_VOICE_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}'s\s+voice\b")
_VOICE_CONTEXT_RE = re.compile(r"\b(?:voice|sound\w*|narrat\w*|speak\w*|talk\w*|perform\w*|impression|style)\b", re.I)
_NAME_PROXIMITY_WINDOW = 40


def _looks_like_a_real_name(phrase: str) -> bool:
    words = phrase.split()
    return not all(w.lower().strip("'s") in _DESCRIPTIVE_WORDS for w in words)


# "My character Sarah Connor" is a fictional-casting request, not a
# real-person request -- exempt a name-shaped match when a character/role
# word appears immediately before it. This does not reopen the bypasses
# above: explicit impersonation phrasing ("sounds like", "in the style of",
# "the guy from"...) is matched independently of this heuristic and stays
# blocked even inside a sentence that also mentions a character.
_CHARACTER_CONTEXT_RE = re.compile(r"\b(?:characters?|protagonist|role\s+of)\b", re.I)
_CHARACTER_CONTEXT_WINDOW = 25


def _names_near_voice_context(text: str) -> bool:
    """True if a name-shaped, capitalized phrase sits close to voice or
    performance vocabulary anywhere in the (original-case) text.
    """
    for match in _PROPER_NAME_RE.finditer(text):
        if not _looks_like_a_real_name(match.group(0)):
            continue
        pre_start = max(0, match.start() - _CHARACTER_CONTEXT_WINDOW)
        if _CHARACTER_CONTEXT_RE.search(text[pre_start:match.start()]):
            continue
        start = max(0, match.start() - _NAME_PROXIMITY_WINDOW)
        end = min(len(text), match.end() + _NAME_PROXIMITY_WINDOW)
        if _VOICE_CONTEXT_RE.search(text[start:end]):
            return True
    return False


def screen_generation_prompt(prompt: str | None) -> SafetyDecision:
    text = (prompt or "").strip()
    if not text:
        return SafetyDecision(True, "synthetic-description", evidence={"prompt_present": False})
    normalized = _normalize_for_screening(text)
    reasons: list[str] = []
    if any(term in normalized for term in _IDENTITY_INTENT_TERMS):
        reasons.append("The request asks for identity deception or exact imitation")
    if any(pattern.search(normalized) for pattern in _IMPERSONATION_PATTERNS):
        reasons.append("Named-person or identity-imitation requests are not allowed in synthetic creation")
    if _POSSESSIVE_VOICE_RE.search(text):
        reasons.append("Requests naming a specific real person's voice are not allowed in synthetic creation")
    elif _names_near_voice_context(text):
        reasons.append(
            "The request appears to name a specific real person alongside voice or "
            "performance language, which is not allowed in synthetic creation"
        )
    if reasons:
        return SafetyDecision(
            False,
            "prohibited-impersonation-intent",
            tuple(reasons),
            {"safe_alternative": "Describe age, pitch, resonance, texture, accent strength, and performance instead of a person."},
        )
    return SafetyDecision(True, "synthetic-description", evidence={"prompt_present": True})


def screen_reference_workflow(
    *,
    feature_enabled: bool,
    authorization_status: str | None,
    consent_document_key: str | None,
    identity_verified: bool,
) -> SafetyDecision:
    reasons: list[str] = []
    if not feature_enabled:
        reasons.append("Reference-voice creation is disabled in this release")
    if authorization_status != "approved":
        reasons.append("An approved speaker authorization is required")
    if not consent_document_key:
        reasons.append("A consent record is required")
    if not identity_verified:
        reasons.append("Speaker identity verification is required")
    return SafetyDecision(
        not reasons,
        "authorized-reference" if not reasons else "reference-blocked",
        tuple(reasons),
    )


def screen_export(*, visibility: str, authenticated: bool, voice_status: str) -> SafetyDecision:
    reasons: list[str] = []
    if not authenticated:
        reasons.append("Anonymous model export is prohibited")
    if visibility == "public":
        reasons.append("Public model export is disabled; use private or organization visibility")
    if voice_status == "revoked":
        reasons.append("Revoked voices cannot be exported or synthesized")
    return SafetyDecision(not reasons, "export-allowed" if not reasons else "export-blocked", tuple(reasons))


def audio_content_fingerprint(audio: bytes) -> str:
    """Cryptographic content fingerprint used in provenance and incident tracing."""
    return hashlib.sha256(audio).hexdigest()


def provenance_manifest(
    *,
    voice_id: str | None,
    voice_version_id: str | None,
    parameter_fingerprint: str,
    audio_fingerprint: str,
    provider: str,
    provider_voice_id: str,
    model_revision: str,
    purpose: str,
) -> dict[str, Any]:
    return {
        "manifest_version": "1.0",
        "classification": "synthetic-generated-audio",
        "voice_id": voice_id,
        "voice_version_id": voice_version_id,
        "parameter_fingerprint": parameter_fingerprint,
        "audio_fingerprint": audio_fingerprint,
        "provider": provider,
        "provider_voice_id": provider_voice_id,
        "model_revision": model_revision,
        "purpose": purpose,
    }


def _profile_vector(parameters: Mapping[str, Any]) -> list[float]:
    paths = [
        "identity.perceived_age",
        "identity.gender_presentation",
        "identity.vocal_weight",
        "identity.pitch_center",
        "identity.pitch_range",
        "identity.warmth",
        "identity.brightness",
        "identity.presence",
        "identity.timbre_complexity",
        "identity.uniqueness",
        "identity.texture.breathiness",
        "identity.texture.roughness",
        "identity.resonance.chest",
        "identity.resonance.mouth",
        "identity.resonance.nasal",
        "identity.resonance.head",
        "performance.energy",
        "performance.expressiveness",
        "performance.authority",
        "performance.intimacy",
        "accent.strength",
    ]
    return [float(get_path(parameters, path, 0.0)) for path in paths]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


class ProtectedVoiceRegistry:
    """Pluggable registry for protected synthetic profiles and provider embeddings.

    ``VOICE_CITY_PROTECTED_PROFILES_JSON`` may contain a JSON object mapping a
    protected identifier to the normalized parameter vector returned by this
    module.  Production deployments can replace this adapter with a true voice-
    embedding service without changing the service/API contract.
    """

    def __init__(self, profiles: Mapping[str, Sequence[float]] | None = None, threshold: float = 0.985):
        self.profiles = {key: [float(v) for v in values] for key, values in (profiles or {}).items()}
        self.threshold = float(threshold)

    @classmethod
    def from_env(cls) -> "ProtectedVoiceRegistry":
        raw = os.getenv("VOICE_CITY_PROTECTED_PROFILES_JSON", "").strip()
        profiles: dict[str, Sequence[float]] = {}
        if raw:
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    profiles = decoded
            except (TypeError, ValueError):
                profiles = {}
        threshold = float(os.getenv("VOICE_CITY_SIMILARITY_THRESHOLD", "0.985"))
        return cls(profiles=profiles, threshold=threshold)

    def check_parameters(self, parameters: Mapping[str, Any]) -> SafetyDecision:
        vector = _profile_vector(parameters)
        strongest_id: str | None = None
        strongest_score = 0.0
        for protected_id, protected_vector in self.profiles.items():
            score = _cosine(vector, protected_vector)
            if score > strongest_score:
                strongest_id, strongest_score = protected_id, score
        if strongest_id and strongest_score >= self.threshold:
            return SafetyDecision(
                False,
                "protected-profile-similarity",
                ("Generated profile is too similar to a protected registry entry",),
                {"protected_id": strongest_id, "score": round(strongest_score, 6), "threshold": self.threshold},
            )
        return SafetyDecision(
            True,
            "similarity-clear",
            evidence={
                "registry_entries": len(self.profiles),
                "strongest_score": round(strongest_score, 6),
                "parameter_fingerprint": canonical_fingerprint(parameters),
            },
        )
