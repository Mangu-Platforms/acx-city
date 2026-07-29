"""Deterministic candidate generation for Voice City.

Voice City is a parametric-catalog system: a voice is an immutable canonical
parameter document (see ``parameter_schema``) plus a mapped provider catalog
voice.  This module turns free-text descriptions into those documents and
produces candidate variations around them.  It is deliberately *not* a
machine-learning component: the mapping from language to controls is an
explicit, reviewable lexicon, and every operation is a pure function of its
inputs.

Guarantees the service layer relies on:

* Determinism.  The same description/seed/count (or base/request/seed) always
  produces identical parameter documents.  All randomness flows through
  ``random.Random`` instances seeded from SHA-256 digests of the inputs; the
  global RNG, wall clock, and network are never consulted.
* Canonical output.  Every returned document has passed
  ``parameter_schema.normalize_parameters``, so it is range-clamped,
  constraint-checked, and carries ``schema_version`` and an integer ``seed``.
* Locked paths win.  Paths locked by the caller stay identical to their
  reference document across every returned candidate, even when a schema
  cross-control constraint would prefer to move them.
"""
from __future__ import annotations

import copy
import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .parameter_schema import (
    CONTROL_BY_PATH,
    SCHEMA_VERSION,
    ControlDefinition,
    artifact_fingerprint,
    get_path,
    merge_parameter_patch,
    normalize_parameters,
    set_parameter_value,
    validate_parameter_paths,
)

#: Catalog mapping revision recorded in candidate fingerprints.  Matches the
#: revision the service stamps on saved versions so an accepted candidate and
#: the version created from it describe the same render identity.
_MODEL_REVISION = "catalog-v1"
_SEED_MODULUS = 2147483647
_MAX_CANDIDATES = 8
#: A single description/mutation term may move a control at most half of its
#: full range; repeated or intensified terms are clamped to the same bound.
_MAX_STEP_FRACTION = 0.5


@dataclass(frozen=True)
class CandidateSpec:
    """One generated voice candidate, ready for persistence by the service."""

    name: str
    parameters: dict[str, Any]
    provider: str
    provider_voice_id: str | None
    quality_score: float
    consistency_score: float
    uniqueness_score: float
    fingerprint: str
    source_versions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic seeding and small numeric helpers
# ---------------------------------------------------------------------------

def _derive_seed(*parts: object) -> int:
    """Derive a stable sub-seed from arbitrary inputs via SHA-256.

    ``hash()`` is randomized per process for strings, so it must never be used
    here.  The digest prefix keeps results identical across runs and machines.
    """
    joined = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % _SEED_MODULUS


def _clamp_value(control: ControlDefinition, value: float) -> float:
    low = float(control.minimum) if control.minimum is not None else value
    high = float(control.maximum) if control.maximum is not None else value
    return round(max(low, min(high, float(value))), 6)


def _bounded_step(control: ControlDefinition, delta: float) -> float:
    if control.minimum is None or control.maximum is None:
        return delta
    cap = _MAX_STEP_FRACTION * (float(control.maximum) - float(control.minimum))
    return max(-cap, min(cap, delta))


def _half_range(control: ControlDefinition) -> float:
    if control.minimum is None or control.maximum is None:
        return 1.0
    return max((float(control.maximum) - float(control.minimum)) / 2.0, 1e-9)


#: Slider defaults that lie outside their own declared range.  The schema
#: ships ``source.creak`` with default -0.15 on a 0..1 scale (a bias toward
#: "no creak"); normalizing any document that carries such a raw default
#: clamps it and emits a warning.  Generated documents pin these paths to
#: their clamped canonical values up front so candidate and preset documents
#: renormalize warning-free.
_RANGE_PINNED_DEFAULTS: dict[str, float] = {
    control.path: round(max(float(control.minimum), min(float(control.maximum), float(control.default))), 6)
    for control in CONTROL_BY_PATH.values()
    if control.control_type == "slider"
    and control.minimum is not None
    and control.maximum is not None
    and not float(control.minimum) <= float(control.default) <= float(control.maximum)
}


# ---------------------------------------------------------------------------
# Description lexicon
#
# Free text is mapped onto schema control paths through an explicit lexicon.
# ``adds`` are additive slider deltas (later scaled by intensifiers and
# flipped by negators); ``sets`` are absolute assignments used for categorical
# controls and for "anchor" slider values such as rhoticity.  Honest
# heuristics only -- unknown words are reported, never guessed at.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Trait:
    adds: tuple[tuple[str, float], ...] = ()
    sets: tuple[tuple[str, Any], ...] = ()


_LEXICON: dict[str, _Trait] = {}


def _lex(
    phrases: str,
    adds: Sequence[tuple[str, float]] = (),
    sets: Sequence[tuple[str, Any]] = (),
) -> None:
    trait = _Trait(adds=tuple(adds), sets=tuple(sets))
    for phrase in phrases.split("|"):
        key = phrase.strip()
        if not key:
            continue
        if key in _LEXICON:
            raise RuntimeError(f"Voice City generator lexicon duplicates {key!r}")
        _LEXICON[key] = trait


# --- gender presentation (convention: negative = masculine, positive = feminine;
#     select_provider_voice applies the same convention when matching catalogs)
_lex("male|man|men|masculine|gentleman|gent", adds=[("identity.gender_presentation", -0.6), ("identity.pitch_center", -0.15)])
_lex("female|woman|women|feminine|lady|ladylike", adds=[("identity.gender_presentation", 0.6), ("identity.pitch_center", 0.15)])
_lex("androgynous|nonbinary|gender neutral|unisex", sets=[("identity.gender_presentation", 0.0), ("identity.pitch_center", 0.0)])
_lex("baritone", adds=[("identity.pitch_center", -0.35), ("identity.gender_presentation", -0.4), ("resonance.low_body", 0.15)])
_lex("bass", adds=[("identity.pitch_center", -0.5), ("identity.gender_presentation", -0.4), ("resonance.low_body", 0.2)])
_lex("tenor", adds=[("identity.pitch_center", -0.1), ("identity.gender_presentation", -0.4)])
_lex("alto|contralto", adds=[("identity.pitch_center", -0.15), ("identity.gender_presentation", 0.4)])
_lex("soprano", adds=[("identity.pitch_center", 0.4), ("identity.gender_presentation", 0.5)])

# --- age
_lex("old|older|elderly|aged|senior|elder|venerable|grizzled|ancient", adds=[("identity.perceived_age", 0.55), ("texture.age_instability", 0.1)])
_lex("grandfather|grandpa|grandfatherly", adds=[("identity.perceived_age", 0.6), ("identity.warmth", 0.15), ("identity.gender_presentation", -0.5)])
_lex("grandmother|grandma|grandmotherly", adds=[("identity.perceived_age", 0.6), ("identity.warmth", 0.15), ("identity.gender_presentation", 0.5)])
_lex("mature|seasoned|weathered|veteran", adds=[("identity.perceived_age", 0.35)])
_lex("middle aged|midlife", adds=[("identity.perceived_age", 0.15)])
_lex("young|younger|youthful", adds=[("identity.perceived_age", -0.45)])
_lex("teenage|teen|adolescent", adds=[("identity.perceived_age", -0.65)])
_lex("childlike|child|kid", adds=[("identity.perceived_age", -0.8), ("identity.pitch_center", 0.2)])
_lex("boyish", adds=[("identity.perceived_age", -0.5), ("identity.gender_presentation", -0.3)])
_lex("girlish", adds=[("identity.perceived_age", -0.5), ("identity.gender_presentation", 0.3)])

# --- pitch, size, and low-end body
_lex("deep|deeper|low|lower|sonorous", adds=[("identity.pitch_center", -0.4), ("identity.body_size", 0.2), ("resonance.low_body", 0.15)])
_lex("booming|thunderous", adds=[("identity.pitch_center", -0.3), ("identity.presence", 0.25), ("source.vocal_effort", 0.2)])
_lex("cavernous", adds=[("identity.pitch_center", -0.25), ("resonance.hollow_quality", 0.25)])
_lex("rumbling|growly|growling|gruff", adds=[("identity.pitch_center", -0.35), ("identity.texture.gravel", 0.3)])
_lex("high|higher|high pitched", adds=[("identity.pitch_center", 0.4)])
_lex("squeaky", adds=[("identity.pitch_center", 0.5), ("identity.vocal_weight", -0.3)])
_lex("resonant", adds=[("resonance.low_body", 0.25), ("identity.timbre_complexity", 0.2)])
_lex("imposing|towering", adds=[("identity.body_size", 0.35), ("identity.presence", 0.25)])
_lex("small|petite", adds=[("identity.body_size", -0.3)])

# --- pace and timing
_lex("slow|slower|slowly|unhurried|leisurely", adds=[("performance.speaking_rate", -0.12), ("timing.pause_duration", 0.15)])
_lex("measured|deliberate|paced", adds=[("performance.speaking_rate", -0.07), ("timing.pause_density", 0.12), ("timing.tempo_stability", 0.1)])
_lex("fast|faster|quick|quickly|rapid|brisk|hurried|snappy", adds=[("performance.speaking_rate", 0.12), ("timing.pause_duration", -0.1)])
_lex("steady|even", adds=[("timing.tempo_stability", 0.15), ("pitch.narrative_stability", 0.1)])
_lex("rhythmic|lilting", adds=[("timing.sentence_rhythm", 0.25), ("pitch.melodic_variation", 0.15)])
_lex("halting|hesitating", adds=[("timing.pause_density", 0.25), ("performance.confidence", -0.2)])

# --- warmth, brightness, and texture
_lex("warm|warmly|warmth|cozy", adds=[("identity.warmth", 0.4)])
_lex("mellow", adds=[("identity.warmth", 0.3), ("identity.brightness", -0.2)])
_lex("cold|icy|clinical|detached|cool", adds=[("identity.warmth", -0.4), ("performance.friendliness", -0.2)])
_lex("gravelly|gravel|gritty", adds=[("identity.texture.gravel", 0.45), ("identity.texture.roughness", 0.15)])
_lex("raspy|rasp|scratchy", adds=[("identity.texture.rasp", 0.4)])
_lex("rough|coarse", adds=[("identity.texture.roughness", 0.35)])
_lex("hoarse", adds=[("identity.texture.roughness", 0.3), ("identity.texture.breathiness", 0.2), ("source.fatigue", 0.15)])
_lex("husky", adds=[("identity.texture.breathiness", 0.25), ("identity.texture.gravel", 0.2), ("identity.pitch_center", -0.1)])
_lex("smoky", adds=[("texture.smokiness", 0.4), ("identity.pitch_center", -0.1)])
_lex("smooth|silky|velvety|velvet|buttery", adds=[("texture.velvet", 0.35), ("identity.texture.roughness", -0.2), ("pitch.contour_smoothness", 0.15)])
_lex("breathy|whispery|whispered|whisper", adds=[("identity.texture.breathiness", 0.35), ("source.vocal_effort", -0.15)])
_lex("airy", adds=[("identity.texture.airiness", 0.3), ("identity.texture.breathiness", 0.15)])
_lex("hushed", adds=[("identity.texture.breathiness", 0.25), ("source.vocal_effort", -0.25), ("performance.intimacy", 0.2)])
_lex("clear|crisp|clean|articulate|precise|enunciated", adds=[("identity.articulation", 0.3), ("articulation.consonant_sharpness", 0.2)])
_lex("mumbly|mumbled|mumbling|slurred", adds=[("articulation.mumbled_quality", 0.3), ("identity.articulation", -0.25)])
_lex("nasal|nasally", adds=[("identity.resonance.nasal", 0.15)])
_lex("rich|full|round|plummy", adds=[("identity.timbre_complexity", 0.25), ("resonance.low_body", 0.2)])
_lex("thin|reedy|wispy", adds=[("identity.vocal_weight", -0.35), ("resonance.low_body", -0.2)])
_lex("light", adds=[("identity.vocal_weight", -0.3)])
_lex("heavy|weighty", adds=[("identity.vocal_weight", 0.35)])
_lex("dark|shadowy", adds=[("identity.brightness", -0.35)])
_lex("bright|brilliant|sparkling|shiny", adds=[("identity.brightness", 0.35)])
_lex("metallic|brassy", adds=[("texture.metallic", 0.3)])
_lex("dry", adds=[("texture.dryness", 0.3)])
_lex("creaky|creaking|vocal fry", adds=[("source.creak", 0.3)])
_lex("polished|refined", adds=[("identity.articulation", 0.25), ("accent.formality", 0.2)])
_lex("distinctive|unique|unusual|memorable", adds=[("identity.uniqueness", 0.3), ("identity.timbre_complexity", 0.15)])

# --- energy, emotion, and stance
_lex("calm|calming|serene|tranquil|relaxed|placid", adds=[("emotion.calm", 0.3), ("performance.energy", -0.2)])
_lex("soothing|comforting|reassuring", adds=[("emotion.reassurance", 0.3), ("emotion.calm", 0.2), ("identity.warmth", 0.15)])
_lex("gentle|gently|tender", adds=[("emotion.tenderness", 0.25), ("source.onset_hardness", -0.15), ("performance.energy", -0.1)])
_lex("energetic|lively|animated|dynamic|vibrant|spirited|peppy|bubbly", adds=[("performance.energy", 0.35), ("performance.excitement", 0.25), ("performance.expressiveness", 0.15)])
_lex("upbeat|enthusiastic", adds=[("performance.energy", 0.3), ("emotion.optimism", 0.2)])
_lex("authoritative|commanding|powerful|assertive", adds=[("performance.authority", 0.35), ("performance.confidence", 0.25), ("identity.presence", 0.2)])
_lex("strong", adds=[("performance.authority", 0.2), ("source.breath_support", 0.15)])
_lex("confident|assured|poised", adds=[("performance.confidence", 0.35)])
_lex("hesitant|timid|shy|nervous", adds=[("performance.confidence", -0.35), ("emotion.embarrassment", 0.15)])
_lex("friendly|approachable|welcoming|kind|amiable|likable", adds=[("performance.friendliness", 0.35)])
_lex("intimate|confiding|personal", adds=[("performance.intimacy", 0.35), ("environment.mic_distance", -0.1), ("environment.proximity_effect", 0.1)])
_lex("close", adds=[("performance.intimacy", 0.25), ("environment.mic_distance", -0.1)])
_lex("distant|aloof|reserved", adds=[("performance.intimacy", -0.3)])
_lex("dramatic|theatrical|grand|epic", adds=[("performance.theatricality", 0.35), ("performance.expressiveness", 0.2), ("narration.dynamic_range", 0.15)])
_lex("understated|restrained|subdued", adds=[("performance.restraint", 0.3), ("performance.theatricality", -0.15)])
_lex("expressive|emotive", adds=[("performance.expressiveness", 0.3), ("pitch.melodic_variation", 0.2)])
_lex("flat|monotone|deadpan", adds=[("performance.expressiveness", -0.3), ("pitch.melodic_variation", -0.2), ("identity.pitch_range", -0.2)])
_lex("cheerful|happy|joyful|merry|sunny", adds=[("emotion.joy", 0.3), ("emotion.optimism", 0.2)])
_lex("sad|somber|sorrowful|mournful", adds=[("performance.sadness", 0.25), ("emotion.melancholy", 0.2), ("performance.energy", -0.15)])
_lex("melancholy|melancholic|wistful", adds=[("emotion.melancholy", 0.3)])
_lex("serious|solemn|grave|earnest", adds=[("emotion.solemnity", 0.3)])
_lex("suspenseful|tense|ominous|foreboding", adds=[("performance.suspense", 0.3), ("narration.suspense_pacing", 0.2)])
_lex("mysterious|eerie|haunting", adds=[("performance.suspense", 0.25), ("performance.intimacy", 0.1), ("identity.brightness", -0.15)])
_lex("playful|humorous|funny|comedic|witty", adds=[("performance.humor", 0.3), ("narration.comedic_timing", 0.2)])
_lex("wry|sardonic", adds=[("emotion.irony", 0.25), ("performance.humor", 0.15)])
_lex("sarcastic|ironic", adds=[("emotion.sarcasm", 0.25), ("emotion.irony", 0.2)])
_lex("soft|quiet|softly", adds=[("source.vocal_effort", -0.25), ("performance.energy", -0.15), ("identity.texture.breathiness", 0.1)])
_lex("loud|projected", adds=[("source.vocal_effort", 0.3), ("identity.presence", 0.2)])
_lex("urgent|insistent|pressing", adds=[("performance.urgency", 0.3)])
_lex("curious|inquisitive|wondering", adds=[("emotion.curiosity", 0.3)])
_lex("awed|reverent", adds=[("emotion.awe", 0.25)])
_lex("proud|dignified", adds=[("emotion.pride", 0.25)])
_lex("empathetic|compassionate|caring", adds=[("emotion.empathy", 0.3), ("emotion.tenderness", 0.15)])
_lex("angry|fierce|forceful", adds=[("emotion.anger", 0.25)])
_lex("fearful|frightened|anxious", adds=[("emotion.fear", 0.25)])
_lex("optimistic|hopeful", adds=[("emotion.optimism", 0.3)])
_lex("weary|tired|fatigued", adds=[("source.fatigue", 0.3), ("performance.energy", -0.2)])
_lex("excited|exciting|thrilling", adds=[("performance.excitement", 0.3)])

# --- register and use case
_lex("conversational|casual|chatty|informal|natural", adds=[("performance.conversationality", 0.3), ("accent.formality", -0.2)])
_lex("formal|professional", adds=[("accent.formality", 0.3), ("identity.articulation", 0.15)])
_lex("storyteller|storytelling", adds=[("narration.fiction_immersion", 0.25), ("performance.expressiveness", 0.2), ("identity.warmth", 0.1)])
_lex("documentary", adds=[("narration.nonfiction_objectivity", 0.25), ("performance.authority", 0.15)])
_lex("meditative|meditation", adds=[("emotion.calm", 0.35), ("performance.speaking_rate", -0.15), ("identity.texture.breathiness", 0.1)])
_lex("children|childrens|kids", adds=[("narration.children_storytelling", 0.4), ("performance.friendliness", 0.2), ("performance.expressiveness", 0.2)])
_lex("broadcaster|newsreader|announcer|broadcast", adds=[("performance.authority", 0.25), ("identity.articulation", 0.2), ("accent.formality", 0.2), ("performance.speaking_rate", 0.05)])
_lex("academic|scholarly|professorial|professor", adds=[("accent.formality", 0.25), ("narration.technical_precision", 0.2), ("identity.perceived_age", 0.15)])
_lex("noir|hardboiled", adds=[("identity.pitch_center", -0.2), ("identity.texture.gravel", 0.2), ("texture.dryness", 0.2), ("performance.suspense", 0.2)])
_lex("memoir|reflective", adds=[("narration.memoir_intimacy", 0.3), ("performance.intimacy", 0.2)])
_lex("advertising|commercial|promo", adds=[("narration.advertising_punch", 0.3), ("performance.energy", 0.2)])

# --- accents and locales (regions are bounded influences, never caricature)
_lex("british|britain|uk|england|londoner", adds=[("accent.strength", 0.25)], sets=[("accent.locale", "en-GB")])
_lex("received pronunciation|rp|posh", adds=[("accent.strength", 0.3), ("accent.formality", 0.15)], sets=[("accent.locale", "en-GB"), ("accent.region", "received-pronunciation"), ("accent.rhoticity", 0.15)])
_lex("cockney", adds=[("accent.strength", 0.4), ("accent.t_glottalization", 0.3), ("accent.h_dropping", 0.2)], sets=[("accent.locale", "en-GB"), ("accent.region", "estuary")])
_lex("estuary", adds=[("accent.strength", 0.25)], sets=[("accent.locale", "en-GB"), ("accent.region", "estuary")])
_lex("yorkshire|mancunian|geordie|northern england", adds=[("accent.strength", 0.35)], sets=[("accent.locale", "en-GB"), ("accent.region", "northern-england")])
_lex("scottish|scots|scotland", adds=[("accent.strength", 0.35)], sets=[("accent.locale", "en-GB"), ("accent.region", "scottish"), ("accent.rhoticity", 0.8)])
_lex("irish|ireland|dublin", adds=[("accent.strength", 0.35)], sets=[("accent.locale", "en-IE"), ("accent.region", "irish"), ("accent.rhoticity", 0.75)])
_lex("australian|aussie|australia", adds=[("accent.strength", 0.3)], sets=[("accent.locale", "en-AU"), ("accent.region", "australian-general")])
_lex("new zealand|kiwi", adds=[("accent.strength", 0.25)], sets=[("accent.locale", "en-NZ")])
_lex("american|usa|yankee|united states", sets=[("accent.locale", "en-US"), ("accent.region", "general")])
_lex("canadian|canada", adds=[("accent.canadian_raising", 0.4)], sets=[("accent.locale", "en-CA")])
_lex("indian|india", adds=[("accent.strength", 0.3)], sets=[("accent.locale", "en-IN"), ("accent.region", "indian-general")])
_lex("south african", adds=[("accent.strength", 0.25)], sets=[("accent.locale", "en-ZA")])
_lex("southern|texan|texas|appalachian|deep south|drawl", adds=[("accent.strength", 0.35), ("accent.pin_pen_merge", 0.3), ("performance.speaking_rate", -0.05)], sets=[("accent.locale", "en-US"), ("accent.region", "southern-us")])
_lex("new england|boston|bostonian", adds=[("accent.strength", 0.3)], sets=[("accent.locale", "en-US"), ("accent.region", "new-england"), ("accent.rhoticity", 0.3)])
_lex("western|californian|midwestern|midwest", adds=[("accent.strength", 0.2)], sets=[("accent.locale", "en-US"), ("accent.region", "western-us")])
_lex("transatlantic|mid atlantic", adds=[("accent.strength", 0.3)], sets=[("accent.locale", "en-US"), ("accent.region", "mid-atlantic"), ("accent.rhoticity", 0.35)])

# --- recognized domain words with no control effect (kept out of warnings)
_lex("narrator|narration|audiobook|voiceover|speaker|reader|voice|tone|accent|delivery|book|books|story|novel|chapter|chapters|speech|speaking")

_INTENSIFIERS: dict[str, float] = {
    "very": 1.5, "extremely": 1.9, "really": 1.4, "so": 1.3, "much": 1.6,
    "way": 1.5, "far": 1.5, "super": 1.6, "incredibly": 1.8, "quite": 1.2,
    "pretty": 1.2, "notably": 1.3, "significantly": 1.5, "dramatically": 1.7,
    "somewhat": 0.6, "slightly": 0.35, "mildly": 0.5, "bit": 0.4,
    "little": 0.4, "touch": 0.35, "tad": 0.35, "subtly": 0.4, "hint": 0.3,
    "marginally": 0.3, "more": 1.25, "extra": 1.4,
}
_NEGATORS = {"not", "no", "never", "less", "without", "non"}
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "with", "of", "in", "on", "for",
    "to", "from", "at", "by", "as", "is", "are", "was", "be", "being", "has",
    "have", "had", "who", "whose", "that", "this", "these", "those", "it",
    "its", "his", "her", "their", "she", "he", "they", "i", "we", "you",
    "me", "my", "your", "like", "sounds", "sound", "sounding", "please",
    "make", "made", "want", "would", "should", "style", "styled", "than",
    "them", "into", "about", "some", "any", "just", "also", "over", "under",
}

_MAX_PHRASE_WORDS = max(len(key.split()) for key in _LEXICON)


def _validate_lexicon() -> None:
    for phrase, trait in _LEXICON.items():
        for path, _delta in trait.adds:
            control = CONTROL_BY_PATH.get(path)
            if control is None or control.control_type != "slider":
                raise RuntimeError(f"Lexicon phrase {phrase!r} targets invalid slider path {path!r}")
        for path, value in trait.sets:
            control = CONTROL_BY_PATH.get(path)
            if control is None:
                raise RuntimeError(f"Lexicon phrase {phrase!r} targets unknown path {path!r}")
            if control.control_type == "select" and value not in control.options:
                raise RuntimeError(f"Lexicon phrase {phrase!r} sets {path!r} to invalid option {value!r}")


_validate_lexicon()


# ---------------------------------------------------------------------------
# Free-text extraction
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STEM_RULES: tuple[tuple[str, str], ...] = (
    ("iest", "y"), ("ier", "y"), ("est", ""), ("er", ""), ("ly", ""),
    ("ness", ""), ("ish", ""), ("ing", ""),
)


def _stem_candidates(token: str) -> list[str]:
    stems = []
    for suffix, replacement in _STEM_RULES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            stems.append(token[: -len(suffix)] + replacement)
    return stems


def _extract_directions(text: str) -> tuple[dict[str, float], dict[str, Any], list[str], list[str]]:
    """Scan text for lexicon traits with intensifier/negator context.

    Returns ``(adds, sets, matched_phrases, unmatched_terms)``.  ``adds`` are
    accumulated slider deltas; ``sets`` are absolute assignments.  Negated
    categorical requests ("not british") are dropped rather than guessed.
    """
    lowered = str(text or "").lower().replace("-", " ").replace("_", " ")
    tokens = _TOKEN_RE.findall(lowered)
    adds: dict[str, float] = {}
    sets: dict[str, Any] = {}
    matched: list[str] = []
    unmatched: list[str] = []
    index = 0
    total = len(tokens)
    while index < total:
        trait: _Trait | None = None
        phrase = ""
        span = 0
        for width in range(min(_MAX_PHRASE_WORDS, total - index), 0, -1):
            candidate = " ".join(tokens[index : index + width])
            found = _LEXICON.get(candidate)
            if found is None and width == 1:
                for stem in _stem_candidates(candidate):
                    found = _LEXICON.get(stem)
                    if found is not None:
                        candidate = stem
                        break
            if found is not None:
                trait, phrase, span = found, candidate, width
                break
        if trait is None:
            token = tokens[index]
            if (
                len(token) > 2
                and token not in _STOPWORDS
                and token not in _INTENSIFIERS
                and token not in _NEGATORS
            ):
                unmatched.append(token)
            index += 1
            continue
        factor = 1.0
        back = index - 1
        for _ in range(3):
            if back < 0:
                break
            previous = tokens[back]
            if previous in _INTENSIFIERS:
                factor *= _INTENSIFIERS[previous]
            elif previous in _NEGATORS:
                factor *= -0.75
            else:
                break
            back -= 1
        factor = max(-2.0, min(2.0, factor))
        matched.append(phrase)
        for path, delta in trait.adds:
            adds[path] = adds.get(path, 0.0) + delta * factor
        if factor > 0:
            for path, value in trait.sets:
                sets[path] = value
        index += span
    deduped = list(dict.fromkeys(unmatched))
    return adds, sets, matched, deduped


def parameters_from_description(
    description: str | None, *, seed: int = 481928
) -> tuple[dict[str, Any], list[str]]:
    """Map a free-text description onto a full canonical parameter document.

    A sparse patch of description-driven controls is built and normalized, so
    untouched paths keep their schema default values exactly (the property
    ``direction_engine`` relies on when diffing against a default baseline).
    The only exception is defaults that sit outside their own declared range
    (see ``_RANGE_PINNED_DEFAULTS``), which are pinned to their clamped
    values; none of those fall under the direction-patch prefixes.  Unknown
    words produce a warning and are otherwise ignored; the function never
    fails on vocabulary.
    """
    document: dict[str, Any] = {"seed": int(seed)}
    for path, pinned in _RANGE_PINNED_DEFAULTS.items():
        set_parameter_value(document, path, pinned)
    text = str(description or "").strip()
    if not text:
        return normalize_parameters(document)
    adds, sets, matched, unmatched = _extract_directions(text)
    for path, delta in adds.items():
        control = CONTROL_BY_PATH[path]
        current = float(_RANGE_PINNED_DEFAULTS.get(path, control.default))
        set_parameter_value(document, path, _clamp_value(control, current + _bounded_step(control, delta)))
    for path, value in sets.items():
        set_parameter_value(document, path, value)
    canonical, norm_warnings = normalize_parameters(document)
    warnings: list[str] = []
    if not matched:
        warnings.append("No recognized voice descriptors were found; schema defaults were used")
    if unmatched:
        warnings.append(
            "Description terms without a control mapping were ignored: " + ", ".join(unmatched[:8])
        )
    return canonical, warnings + norm_warnings


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_EXTREMITY_PATHS = (
    "identity.pitch_center", "identity.perceived_age", "identity.vocal_weight",
    "identity.gender_presentation", "identity.body_size", "performance.speaking_rate",
    "performance.energy", "source.vocal_effort", "resonance.formant_shift",
    "resonance.formant_spread",
)
_STABILITY_PATHS = (
    "source.stability", "timing.tempo_stability", "accent.consistency",
    "texture.long_form_consistency", "pitch.narrative_stability",
    "articulation.enunciation_consistency", "narration.long_form_identity_lock",
    "narration.chapter_memory",
)
_VOLATILITY_PATHS = (
    "emotion.volatility", "pitch.random_drift", "source.micro_irregularity",
    "timing.rubato", "texture.jitter", "texture.shimmer_variation",
    "source.fatigue", "texture.age_instability",
)
_IDENTITY_SPREAD_PATHS = (
    "identity.pitch_center", "identity.perceived_age", "identity.gender_presentation",
    "identity.vocal_weight", "identity.warmth", "identity.brightness",
    "identity.body_size", "identity.presence", "resonance.low_body",
    "resonance.forward_placement", "source.spectral_tilt", "source.register_mix",
)
_TEXTURE_SPREAD_PATHS = (
    "identity.texture.breathiness", "identity.texture.roughness",
    "identity.texture.rasp", "identity.texture.gravel", "identity.texture.airiness",
    "texture.velvet", "texture.smokiness", "texture.dryness", "texture.metallic",
)


def _value(canonical: Mapping[str, Any], path: str) -> float:
    control = CONTROL_BY_PATH[path]
    return float(get_path(canonical, path, control.default))


def _mean_default_deviation(canonical: Mapping[str, Any], paths: Sequence[str]) -> float:
    total = 0.0
    for path in paths:
        control = CONTROL_BY_PATH[path]
        deviation = abs(_value(canonical, path) - float(control.default)) / _half_range(control)
        total += min(1.0, deviation)
    return total / len(paths)


def score_parameters(canonical: Mapping[str, Any]) -> tuple[float, float, float]:
    """Score a canonical document; returns ``(quality, consistency, uniqueness)``.

    All three are deterministic values in ``[0, 1]`` computed only from the
    document -- no audio is rendered.

    * ``quality`` starts at 1.0 and pays for distance from the well-tested
      catalog center: extreme identity settings, heavy texture stacks,
      mumble, wet rooms, spoken vibrato, and instability all reduce the
      likelihood that the provider mapping renders faithfully.
    * ``consistency`` reflects long-form repeatability: the schema's explicit
      stability controls raise it, volatility/irregularity controls and
      internally contradictory pairings (pressed yet breathy, calm yet
      urgent, joyful yet melancholic, fast yet pause-dense) lower it.
    * ``uniqueness`` measures departure from the default catalog voice:
      spread of identity and texture controls away from schema defaults plus
      the explicit uniqueness/timbre-complexity dials and accent character.
    """
    extremity = _mean_default_deviation(canonical, _EXTREMITY_PATHS)
    texture_load = min(
        1.0,
        (
            _value(canonical, "identity.texture.roughness")
            + _value(canonical, "identity.texture.rasp")
            + _value(canonical, "identity.texture.gravel")
            + 0.5 * _value(canonical, "texture.smokiness")
            + 0.5 * _value(canonical, "texture.metallic")
        )
        / 1.75,
    )
    mumble_load = min(1.0, _value(canonical, "articulation.mumbled_quality") / 0.55)
    room_load = 0.5 * min(1.0, _value(canonical, "environment.room_liveness") / 0.45) + 0.5 * min(
        1.0, _value(canonical, "environment.reverb_decay") / 0.35
    )
    vibrato_load = min(
        1.0, (_value(canonical, "pitch.vibrato") * _value(canonical, "pitch.vibrato_depth")) / 0.18
    )
    instability = min(1.0, sum(_value(canonical, path) for path in _VOLATILITY_PATHS) / 1.5)
    quality = 1.0 - (
        0.30 * extremity
        + 0.20 * texture_load
        + 0.15 * mumble_load
        + 0.10 * room_load
        + 0.10 * vibrato_load
        + 0.15 * instability
    )

    stability = sum(_value(canonical, path) for path in _STABILITY_PATHS) / len(_STABILITY_PATHS)
    volatility = sum(_value(canonical, path) for path in _VOLATILITY_PATHS) / len(_VOLATILITY_PATHS)
    breathiness = _value(canonical, "identity.texture.breathiness")
    pressed = max(_value(canonical, "source.vocal_effort"), _value(canonical, "source.fold_closure"))
    conflict = 0.8 * max(0.0, breathiness - 0.5) * max(0.0, pressed - 0.4)
    for left, right in (
        ("performance.energy", "emotion.calm"),
        ("performance.urgency", "emotion.calm"),
        ("emotion.joy", "emotion.melancholy"),
        ("performance.excitement", "performance.sadness"),
    ):
        conflict += 0.25 * min(max(0.0, _value(canonical, left)), max(0.0, _value(canonical, right)))
    rate = _value(canonical, "performance.speaking_rate")
    conflict += 0.5 * max(0.0, rate - 1.15) * max(0.0, _value(canonical, "timing.pause_density") - 0.5)
    conflict = min(0.4, conflict)
    consistency = 0.35 + 0.65 * stability - 0.35 * volatility - conflict

    identity_spread = _mean_default_deviation(canonical, _IDENTITY_SPREAD_PATHS)
    texture_spread = _mean_default_deviation(canonical, _TEXTURE_SPREAD_PATHS)
    accent_character = min(
        1.0,
        _value(canonical, "accent.strength")
        + (0.15 if str(get_path(canonical, "accent.region", "general")) != "general" else 0.0),
    )
    uniqueness = (
        0.12
        + 0.40 * identity_spread
        + 0.18 * texture_spread
        + 0.22 * _value(canonical, "identity.uniqueness")
        + 0.08 * _value(canonical, "identity.timbre_complexity")
        + 0.10 * accent_character
    )

    def _finish(value: float) -> float:
        return round(min(1.0, max(0.0, value)), 4)

    return _finish(quality), _finish(consistency), _finish(uniqueness)


# ---------------------------------------------------------------------------
# Provider voice selection
# ---------------------------------------------------------------------------

#: Stable fallbacks when a provider's live catalog is unavailable.  Edge ids
#: mirror its curated offline list; Polly ids are long-standing catalog names.
_FALLBACK_VOICE_IDS: dict[str, dict[str, dict[str, str]]] = {
    "edge": {
        "en-US": {"male": "en-US-AndrewNeural", "female": "en-US-AvaNeural", "any": "en-US-AvaNeural"},
        "en-GB": {"male": "en-GB-RyanNeural", "female": "en-GB-SoniaNeural", "any": "en-GB-SoniaNeural"},
        "en-AU": {"male": "en-AU-WilliamNeural", "female": "en-AU-NatashaNeural", "any": "en-AU-NatashaNeural"},
        "en-IN": {"male": "en-IN-PrabhatNeural", "female": "en-IN-NeerjaNeural", "any": "en-IN-NeerjaNeural"},
    },
    "polly": {
        "en-US": {"male": "Matthew", "female": "Joanna", "any": "Joanna"},
        "en-GB": {"male": "Brian", "female": "Amy", "any": "Amy"},
        "en-AU": {"male": "Russell", "female": "Nicole", "any": "Nicole"},
        "en-IN": {"male": "Raveena", "female": "Raveena", "any": "Raveena"},
    },
}
_LOCALE_COUSINS = {"en-CA": "en-US", "en-IE": "en-GB", "en-NZ": "en-AU", "en-ZA": "en-GB"}


def _gender_target(canonical: Mapping[str, Any]) -> str | None:
    presentation = float(get_path(canonical, "identity.gender_presentation", 0.0))
    if presentation <= -0.12:
        return "male"
    if presentation >= 0.12:
        return "female"
    return None


def select_provider_voice(
    canonical: Mapping[str, Any],
    *,
    provider: str,
    available_voices: Sequence[Mapping[str, Any]] | None,
) -> str:
    """Pick a provider catalog voice for a canonical document, deterministically.

    Matches the document's identity controls against the provider's
    ``list_voices()`` dicts (``{id, name, language, gender, neural}``): exact
    locale beats language-prefix matches, gender presentation (negative =
    masculine, positive = feminine) beats neutral, and neural voices get a
    small preference.  Catalog dicts carry no age metadata, so age is not
    matched.  Ties break on the voice id string, so the choice is stable for
    a given document and catalog.  With no catalog at all, a curated
    per-provider fallback table keyed by locale and gender is used.
    """
    locale = str(get_path(canonical, "accent.locale", "en-US"))
    target = _gender_target(canonical)
    entries = list(available_voices or ())
    scored: list[tuple[float, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        voice_id = str(entry.get("id") or entry.get("voice_id") or entry.get("name") or "").strip()
        if not voice_id:
            continue
        language = str(entry.get("language") or entry.get("locale") or "")
        gender = str(entry.get("gender") or "").strip().lower()
        score = 0.0
        if language.lower() == locale.lower():
            score += 3.0
        elif language.lower().split("-")[0] == locale.lower().split("-")[0]:
            score += 1.5
        if target is None:
            score += 0.5
        elif gender == target:
            score += 2.0
        if entry.get("neural"):
            score += 0.25
        scored.append((score, voice_id))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]
    table = _FALLBACK_VOICE_IDS.get(str(provider or "").lower())
    if table:
        by_locale = table.get(locale) or table.get(_LOCALE_COUSINS.get(locale, "")) or table.get("en-US")
        if by_locale:
            return by_locale.get(target or "any") or by_locale["any"]
    return "default"


# ---------------------------------------------------------------------------
# Deterministic candidate names
# ---------------------------------------------------------------------------

_NAME_ADJECTIVES = (
    "Amber", "Ashen", "Autumn", "Briar", "Bright", "Cedar", "Cinder", "Cobalt",
    "Copper", "Coral", "Crimson", "Dove", "Dusk", "Ember", "Fern", "Flint",
    "Garnet", "Gilded", "Hazel", "Indigo", "Iron", "Ivory", "Jade", "Juniper",
    "Lark", "Linen", "Maple", "Marble", "Meadow", "Midnight", "Mist", "Moss",
    "Oak", "Ochre", "Onyx", "Opal", "Pewter", "Quartz", "Raven", "River",
    "Saffron", "Sable", "Sage", "Scarlet", "Sepia", "Silver", "Slate",
    "Sterling", "Thistle", "Topaz", "Umber", "Velvet", "Violet", "Willow",
)
_NAME_NOUNS = (
    "Anthem", "Atlas", "Ballad", "Beacon", "Bell", "Bloom", "Breeze", "Brook",
    "Cadence", "Canyon", "Cascade", "Chord", "Chronicle", "Compass", "Cove",
    "Creek", "Crest", "Crown", "Dawn", "Drift", "Echo", "Fjord", "Garden",
    "Grove", "Harbor", "Haven", "Hollow", "Horizon", "Lantern", "Ledger",
    "Lyric", "Meridian", "Orchard", "Prairie", "Quill", "Refrain", "Ridge",
    "Sonnet", "Spire", "Summit", "Tide", "Trail", "Verse", "Vista", "Waltz",
)


def _candidate_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(12):
        name = f"{rng.choice(_NAME_ADJECTIVES)} {rng.choice(_NAME_NOUNS)}"
        if name not in used:
            return name
    return f"{rng.choice(_NAME_ADJECTIVES)} {rng.choice(_NAME_NOUNS)} {len(used) + 1}"


# ---------------------------------------------------------------------------
# Spec assembly and lock enforcement
# ---------------------------------------------------------------------------

def _enforce_locks(
    canonical: dict[str, Any],
    reference: Mapping[str, Any],
    locked: Sequence[str],
) -> tuple[dict[str, Any], list[str]]:
    """Hold ``locked`` paths at their reference values after normalization.

    Normalization can move a locked value through a cross-control constraint
    (for example, high breathiness capping vocal effort).  Locks take
    priority: drifted paths are restored and the document renormalized once;
    if a constraint keeps fighting, the locked values are restored anyway and
    a warning explains that a schema constraint was overridden by the lock.
    """
    def _drifted(document: Mapping[str, Any]) -> list[str]:
        return [
            path
            for path in locked
            if get_path(document, path) != get_path(reference, path)
        ]

    warnings: list[str] = []
    moved = _drifted(canonical)
    if not moved:
        return canonical, warnings
    for path in moved:
        set_parameter_value(canonical, path, copy.deepcopy(get_path(reference, path)))
    renormalized, _ = normalize_parameters(canonical)
    still_moved = _drifted(renormalized)
    if still_moved:
        for path in still_moved:
            set_parameter_value(renormalized, path, copy.deepcopy(get_path(reference, path)))
        warnings.append(
            "Locked paths were held despite schema cross-constraints: "
            + ", ".join(sorted(still_moved))
        )
    return renormalized, warnings


def _finalize_spec(
    parameters: Mapping[str, Any],
    *,
    provider: str,
    available_voices: Sequence[Mapping[str, Any]] | None,
    name: str,
    source_versions: Sequence[str],
    warnings: Sequence[str],
    locked: Sequence[str] = (),
    reference: Mapping[str, Any] | None = None,
) -> CandidateSpec:
    canonical, norm_warnings = normalize_parameters(parameters)
    lock_warnings: list[str] = []
    if locked and reference is not None:
        canonical, lock_warnings = _enforce_locks(canonical, reference, locked)
    provider_voice_id = select_provider_voice(
        canonical, provider=provider, available_voices=available_voices
    )
    quality, consistency, uniqueness = score_parameters(canonical)
    combined = list(dict.fromkeys([*warnings, *norm_warnings, *lock_warnings]))
    return CandidateSpec(
        name=name,
        parameters=canonical,
        provider=str(provider),
        provider_voice_id=provider_voice_id,
        quality_score=quality,
        consistency_score=consistency,
        uniqueness_score=uniqueness,
        fingerprint=artifact_fingerprint(
            canonical,
            provider=str(provider),
            provider_voice_id=provider_voice_id,
            model_revision=_MODEL_REVISION,
        ),
        source_versions=list(source_versions),
        warnings=combined,
    )


# ---------------------------------------------------------------------------
# Public operations: generate, mutate, breed
# ---------------------------------------------------------------------------

#: Paths jittered when exploring around a described center, with per-path
#: sigmas in native control units.  Identity-defining controls (gender,
#: texture) get small sigmas so variations stay recognizably "the same brief".
_VARIATION_PALETTE: tuple[tuple[str, float], ...] = (
    ("identity.perceived_age", 0.10),
    ("identity.gender_presentation", 0.05),
    ("identity.vocal_weight", 0.12),
    ("identity.pitch_center", 0.10),
    ("identity.pitch_range", 0.08),
    ("identity.warmth", 0.12),
    ("identity.brightness", 0.12),
    ("identity.timbre_complexity", 0.10),
    ("identity.uniqueness", 0.10),
    ("identity.body_size", 0.10),
    ("identity.presence", 0.10),
    ("identity.texture.breathiness", 0.06),
    ("identity.texture.roughness", 0.05),
    ("identity.texture.airiness", 0.05),
    ("texture.velvet", 0.08),
    ("resonance.low_body", 0.10),
    ("resonance.forward_placement", 0.08),
    ("pitch.melodic_variation", 0.08),
    ("pitch.contour_smoothness", 0.08),
    ("performance.speaking_rate", 0.05),
    ("performance.energy", 0.10),
    ("performance.expressiveness", 0.08),
    ("performance.intimacy", 0.10),
    ("performance.authority", 0.10),
    ("performance.confidence", 0.08),
    ("timing.pause_density", 0.06),
    ("timing.pause_duration", 0.08),
    ("source.spectral_tilt", 0.08),
    ("source.register_mix", 0.08),
)
for _path, _sigma in _VARIATION_PALETTE:
    if _path not in CONTROL_BY_PATH:
        raise RuntimeError(f"Variation palette references unknown path {_path!r}")

#: Jitter multiplier per candidate ordinal; index 0 is the literal center.
_SPREAD_BY_INDEX = (0.0, 0.7, 0.85, 1.0, 1.1, 1.2, 1.3, 1.4)


def generate_candidates(
    *,
    description: str | None,
    provider: str,
    count: int,
    seed: int,
    locked_paths: Sequence[str],
    available_voices: Sequence[Mapping[str, Any]] | None,
) -> list[CandidateSpec]:
    """Generate up to eight diverse candidates around a described center.

    Candidate 0 is the literal reading of the description; later candidates
    apply progressively wider deterministic jitter from the variation palette.
    Locked paths are identical (equal to the center's value) across every
    candidate.  Candidate ``i`` depends only on ``(description, seed, i)``,
    so requesting a larger count extends -- never reshuffles -- a smaller one.
    """
    requested = max(1, min(_MAX_CANDIDATES, int(count)))
    locked = validate_parameter_paths(list(locked_paths or ()))
    center, center_warnings = parameters_from_description(description, seed=int(seed))
    center_seed = int(center["seed"])
    specs: list[CandidateSpec] = []
    used_names: set[str] = set()
    for index in range(requested):
        candidate_seed = _derive_seed("voice-city", "generate", center_seed, index)
        name_rng = random.Random(_derive_seed("voice-city", "name", center_seed, index))
        name = _candidate_name(name_rng, used_names)
        used_names.add(name)
        patch: dict[str, Any] = {}
        if index > 0:
            jitter_rng = random.Random(candidate_seed)
            spread = _SPREAD_BY_INDEX[min(index, len(_SPREAD_BY_INDEX) - 1)]
            for path, sigma in _VARIATION_PALETTE:
                if path in locked:
                    continue
                control = CONTROL_BY_PATH[path]
                jitter = jitter_rng.uniform(-1.0, 1.0) * sigma * spread
                current = float(get_path(center, path, control.default))
                set_parameter_value(patch, path, _clamp_value(control, current + jitter))
        merged, merge_warnings = merge_parameter_patch(center, patch, seed=candidate_seed)
        specs.append(
            _finalize_spec(
                merged,
                provider=provider,
                available_voices=available_voices,
                name=name,
                source_versions=[],
                warnings=[*center_warnings, *merge_warnings],
                locked=locked,
                reference=center,
            )
        )
    return specs


def mutate_candidate(
    *,
    base: Mapping[str, Any],
    request: str | None,
    provider: str,
    available_voices: Sequence[Mapping[str, Any]] | None,
    seed: int | None,
    locked_paths: Sequence[str],
    source_versions: Sequence[str],
) -> CandidateSpec:
    """Apply a natural-language adjustment ("warmer, much slower") to a base doc.

    Directional terms move controls by bounded deltas relative to the *base*
    values (not schema defaults); intensifiers scale and negators invert the
    step.  Locked paths are never modified, and requests that target them are
    reported instead of applied.  When ``seed`` is None a deterministic seed
    is derived from the base document's seed and the request text.
    """
    locked = validate_parameter_paths(list(locked_paths or ()))
    base_doc, base_warnings = normalize_parameters(base)
    request_text = str(request or "").strip()
    if seed is None:
        effective_seed = _derive_seed("voice-city", "mutate", base_doc["seed"], request_text.lower())
    else:
        effective_seed = int(seed)
    adds, sets, matched, unmatched = _extract_directions(request_text)
    warnings: list[str] = list(base_warnings)
    patch: dict[str, Any] = {}
    blocked: list[str] = []
    for path, delta in adds.items():
        if path in locked:
            blocked.append(path)
            continue
        control = CONTROL_BY_PATH[path]
        current = float(get_path(base_doc, path, control.default))
        set_parameter_value(patch, path, _clamp_value(control, current + _bounded_step(control, delta)))
    for path, value in sets.items():
        if path in locked:
            blocked.append(path)
            continue
        set_parameter_value(patch, path, value)
    if blocked:
        warnings.append(
            "Requested changes to locked paths were ignored: " + ", ".join(sorted(set(blocked)))
        )
    if not matched:
        warnings.append("No recognized direction terms in the request; only the seed changed")
    if unmatched:
        warnings.append(
            "Request terms without a control mapping were ignored: " + ", ".join(unmatched[:8])
        )
    merged, merge_warnings = merge_parameter_patch(base_doc, patch, seed=effective_seed)
    name_rng = random.Random(_derive_seed("voice-city", "name", "mutate", effective_seed))
    return _finalize_spec(
        merged,
        provider=provider,
        available_voices=available_voices,
        name=_candidate_name(name_rng, set()),
        source_versions=list(source_versions),
        warnings=[*warnings, *merge_warnings],
        locked=locked,
        reference=base_doc,
    )


def breed_candidate(
    *,
    parent_a: Mapping[str, Any],
    parent_b: Mapping[str, Any],
    provider: str,
    weight_a: float,
    seed: int,
    available_voices: Sequence[Mapping[str, Any]] | None,
    locked_from_a: Sequence[str],
    source_versions: Sequence[str],
) -> CandidateSpec:
    """Blend two canonical documents into one deterministic offspring.

    Numeric controls interpolate ``a * weight_a + b * (1 - weight_a)``;
    categorical and toggle controls copy parent A when ``weight_a >= 0.5``
    and parent B otherwise.  Paths in ``locked_from_a`` always copy parent A
    regardless of weight.  The blend is rebuilt control-by-control and then
    normalized, so the offspring is always a clean canonical document.
    """
    locked = validate_parameter_paths(list(locked_from_a or ()))
    doc_a, _warnings_a = normalize_parameters(parent_a)
    doc_b, _warnings_b = normalize_parameters(parent_b)
    weight = min(1.0, max(0.0, float(weight_a)))
    blended: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "seed": int(seed)}
    for path, control in CONTROL_BY_PATH.items():
        value_a = get_path(doc_a, path, control.default)
        value_b = get_path(doc_b, path, control.default)
        if path in locked:
            value: Any = value_a
        elif control.control_type == "slider":
            value = round(float(value_a) * weight + float(value_b) * (1.0 - weight), 6)
        else:
            value = value_a if weight >= 0.5 else value_b
        set_parameter_value(blended, path, copy.deepcopy(value))
    name_rng = random.Random(_derive_seed("voice-city", "name", "breed", int(seed), weight))
    return _finalize_spec(
        blended,
        provider=provider,
        available_voices=available_voices,
        name=_candidate_name(name_rng, set()),
        source_versions=list(source_versions),
        warnings=[],
        locked=locked,
        reference=doc_a,
    )
