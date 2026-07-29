"""Versioned, semantic parameter schema for Voice City.

Voice City exposes meaningful sound-design controls and translates them to a
smaller provider/model contract.  It never exposes raw neural-network weights.
Every saved voice version is an immutable canonical JSON document produced by
``normalize_parameters``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"
MODE_RANK = {"simple": 0, "studio": 1, "laboratory": 2}

GROUPS = [
    {"id": "source", "title": "Source & vocal folds", "order": 1, "description": "Vocal-fold behavior, effort, closure, and source character."},
    {"id": "resonance", "title": "Formants & resonance", "order": 2, "description": "Perceived vocal tract, body size, placement, and harmonic color."},
    {"id": "pitch", "title": "Pitch & melody", "order": 3, "description": "Pitch center, range, contour, cadence, and melodic movement."},
    {"id": "timing", "title": "Timing & rhythm", "order": 4, "description": "Rate, phrase architecture, pauses, rhythm, and resets."},
    {"id": "articulation", "title": "Articulation", "order": 5, "description": "Diction, consonants, vowels, reduction, and intelligibility."},
    {"id": "breath_texture", "title": "Breath & texture", "order": 6, "description": "Breath events, air, rasp, grain, shimmer, and vocal noise."},
    {"id": "emotion", "title": "Emotion", "order": 7, "description": "Performance affect, intensity, restraint, and interpersonal stance."},
    {"id": "accent", "title": "Accent & phonology", "order": 8, "description": "Locale, regional influence, phonological behavior, and code switching."},
    {"id": "narration", "title": "Narration behavior", "order": 9, "description": "Text-dependent delivery, dialogue, lists, quotations, and scene behavior."},
    {"id": "environment", "title": "Recording environment", "order": 10, "description": "Virtual microphone, distance, room, and spatial presentation."},
    {"id": "post", "title": "Post-processing", "order": 11, "description": "Loudness, dynamics, tonal finishing, de-essing, and output polish."},
    {"id": "interpretation", "title": "Text interpretation", "order": 12, "description": "Names, dates, acronyms, symbols, markup, and semantic reading rules."},
]


class ParameterValidationError(ValueError):
    """Raised when a parameter document cannot be made safe and canonical."""


@dataclass(frozen=True)
class ControlDefinition:
    path: str
    label: str
    group: str
    control_type: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None
    mode: str = "laboratory"
    description: str = ""
    audible_impact: str = ""
    options: tuple[str, ...] = ()
    automatable: bool = True
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "group": self.group,
            "control_type": self.control_type,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "unit": self.unit,
            "mode": self.mode,
            "description": self.description,
            "audible_impact": self.audible_impact,
            "options": list(self.options),
            "automatable": self.automatable,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
        }


_CONTROLS: list[ControlDefinition] = []


def slider(
    path: str,
    label: str,
    group: str,
    default: float = 0.0,
    minimum: float = -1.0,
    maximum: float = 1.0,
    step: float = 0.01,
    unit: str | None = None,
    mode: str = "laboratory",
    description: str = "",
    audible_impact: str = "",
    aliases: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> None:
    _CONTROLS.append(
        ControlDefinition(
            path=path,
            label=label,
            group=group,
            control_type="slider",
            default=default,
            minimum=minimum,
            maximum=maximum,
            step=step,
            unit=unit,
            mode=mode,
            description=description or f"Controls {label.lower()} in the generated performance.",
            audible_impact=audible_impact or f"Higher values increase {label.lower()}; lower values reduce it.",
            aliases=tuple(aliases),
            tags=tuple(tags),
        )
    )


def select(
    path: str,
    label: str,
    group: str,
    default: str,
    options: Sequence[str],
    mode: str = "laboratory",
    description: str = "",
    audible_impact: str = "",
    automatable: bool = False,
    aliases: Sequence[str] = (),
) -> None:
    _CONTROLS.append(
        ControlDefinition(
            path=path,
            label=label,
            group=group,
            control_type="select",
            default=default,
            mode=mode,
            description=description or f"Selects the {label.lower()} behavior.",
            audible_impact=audible_impact or f"Changes how {label.lower()} is interpreted.",
            options=tuple(options),
            automatable=automatable,
            aliases=tuple(aliases),
        )
    )


def toggle(
    path: str,
    label: str,
    group: str,
    default: bool = False,
    mode: str = "laboratory",
    description: str = "",
    audible_impact: str = "",
    automatable: bool = False,
) -> None:
    _CONTROLS.append(
        ControlDefinition(
            path=path,
            label=label,
            group=group,
            control_type="toggle",
            default=default,
            mode=mode,
            description=description or f"Enables {label.lower()}.",
            audible_impact=audible_impact or f"When enabled, {label.lower()} affects delivery.",
            automatable=automatable,
        )
    )


# ---------------------------------------------------------------------------
# 1. Source and vocal folds
# ---------------------------------------------------------------------------
slider("identity.perceived_age", "Perceived age", "source", 0.0, -1.0, 1.0, mode="simple", audible_impact="Moves the impression from youthful to elderly without naming a real speaker.")
slider("identity.gender_presentation", "Gender presentation", "source", 0.0, -1.0, 1.0, mode="simple", audible_impact="Continuously shifts perceived vocal presentation rather than choosing a categorical label.")
slider("identity.vocal_weight", "Vocal weight", "source", 0.0, -1.0, 1.0, mode="simple", audible_impact="Moves from light and delicate to heavy and substantial.")
slider("source.fold_closure", "Vocal-fold closure", "source", 0.05, -1.0, 1.0, mode="studio", audible_impact="Moves from soft/leaky closure to firm/pressed closure.")
slider("source.vocal_effort", "Vocal effort", "source", 0.0, -1.0, 1.0, mode="studio", audible_impact="Changes how hard the speaker appears to drive the voice.")
slider("source.breath_support", "Breath support", "source", 0.2, -1.0, 1.0, mode="studio", audible_impact="Affects steadiness and the sense of supported projection.")
slider("source.creak", "Creak", "source", -0.15, 0.0, 1.0, mode="studio", audible_impact="Adds low, irregular vocal-fry character, especially at phrase edges.")
slider("source.pressure", "Subglottal pressure", "source", 0.0, -1.0, 1.0, audible_impact="Changes source drive and apparent projection pressure.")
slider("source.closure_speed", "Closure speed", "source", 0.0, -1.0, 1.0, audible_impact="Faster closure sharpens the source; slower closure softens attacks.")
slider("source.open_quotient", "Open quotient", "source", 0.0, -1.0, 1.0, audible_impact="Higher values create a more open, airy source; lower values sound compact.")
slider("source.spectral_tilt", "Source spectral tilt", "source", 0.0, -1.0, 1.0, audible_impact="Balances mellow high-frequency roll-off against a brighter source spectrum.")
slider("source.glottal_tension", "Glottal tension", "source", 0.0, -1.0, 1.0, audible_impact="Adds tautness or relaxation to the vocal source.")
slider("source.onset_hardness", "Onset hardness", "source", -0.05, -1.0, 1.0, audible_impact="Controls whether syllables begin gently or with a firm attack.")
slider("source.offset_hardness", "Offset hardness", "source", -0.1, -1.0, 1.0, audible_impact="Controls whether phrase endings release softly or stop firmly.")
slider("source.register_mix", "Register mix", "source", 0.0, -1.0, 1.0, audible_impact="Balances chest-dominant and head-dominant source behavior.")
slider("source.chest_register", "Chest-register bias", "source", 0.1, -1.0, 1.0, audible_impact="Adds grounded lower-register character.")
slider("source.head_register", "Head-register bias", "source", -0.05, -1.0, 1.0, audible_impact="Adds lighter upper-register character.")
slider("source.stability", "Source stability", "source", 0.55, 0.0, 1.0, audible_impact="Higher values resist unintended source drift across long narration.")
slider("source.micro_irregularity", "Micro-irregularity", "source", 0.08, 0.0, 1.0, audible_impact="Adds subtle nonperiodic variation that can reduce synthetic perfection.")
slider("source.fatigue", "Vocal fatigue", "source", 0.0, 0.0, 1.0, audible_impact="Adds controlled signs of tired vocal production.")

# ---------------------------------------------------------------------------
# 2. Formants and resonance
# ---------------------------------------------------------------------------
slider("identity.pitch_center", "Pitch center", "pitch", 0.0, -1.0, 1.0, mode="simple", audible_impact="Moves the overall perceived pitch center lower or higher.")
slider("identity.body_size", "Body-size impression", "resonance", 0.0, -1.0, 1.0, mode="studio", audible_impact="Moves from a small vocal-tract impression to an imposing one.")
slider("identity.warmth", "Warmth", "resonance", 0.25, -1.0, 1.0, mode="simple", audible_impact="Moves from clinical/cool to intimate/warm resonance.")
slider("identity.brightness", "Brightness", "resonance", 0.0, -1.0, 1.0, mode="simple", audible_impact="Moves from dark/mellow to brilliant/forward.")
slider("identity.presence", "Presence", "resonance", 0.1, -1.0, 1.0, mode="studio", audible_impact="Moves from distant to commanding and immediate.")
slider("identity.timbre_complexity", "Timbre complexity", "resonance", 0.25, 0.0, 1.0, mode="studio", audible_impact="Moves from a pure/simple tone to harmonically rich color.")
slider("identity.uniqueness", "Uniqueness", "resonance", 0.25, 0.0, 1.0, mode="studio", audible_impact="Increases departure from conventional catalog-voice character while staying stable.")
slider("identity.resonance.chest", "Chest resonance", "resonance", 0.35, 0.0, 1.0, mode="studio", audible_impact="Adds grounded low-frequency body.")
slider("identity.resonance.throat", "Throat resonance", "resonance", 0.15, 0.0, 1.0, mode="studio", audible_impact="Adds pharyngeal focus and compactness.")
slider("identity.resonance.mouth", "Mouth resonance", "resonance", 0.30, 0.0, 1.0, mode="studio", audible_impact="Adds oral clarity and speech-like focus.")
slider("identity.resonance.nasal", "Nasal resonance", "resonance", 0.05, 0.0, 1.0, mode="studio", audible_impact="Adds controlled nasal coupling; excessive values are constrained.")
slider("identity.resonance.head", "Head resonance", "resonance", 0.15, 0.0, 1.0, mode="studio", audible_impact="Adds upper resonance and lightness.")
slider("resonance.formant_shift", "Global formant shift", "resonance", 0.0, -1.0, 1.0, audible_impact="Shifts perceived vocal-tract size independently of pitch.")
slider("resonance.formant_spread", "Formant spread", "resonance", 0.0, -1.0, 1.0, audible_impact="Changes spacing between resonance bands and apparent tract shape.")
slider("resonance.f1_bias", "First-formant bias", "resonance", 0.0, -1.0, 1.0, audible_impact="Changes vowel openness and lower resonance emphasis.")
slider("resonance.f2_bias", "Second-formant bias", "resonance", 0.0, -1.0, 1.0, audible_impact="Changes front/back vowel color and oral focus.")
slider("resonance.f3_bias", "Third-formant bias", "resonance", 0.0, -1.0, 1.0, audible_impact="Changes upper vocal color and perceived speaker signature.")
slider("resonance.f4_bias", "Fourth-formant bias", "resonance", 0.0, -1.0, 1.0, audible_impact="Changes high resonance detail and brilliance.")
slider("resonance.pharyngeal_focus", "Pharyngeal focus", "resonance", 0.0, -1.0, 1.0, audible_impact="Adds or reduces deep throat placement.")
slider("resonance.oral_focus", "Oral focus", "resonance", 0.1, -1.0, 1.0, audible_impact="Moves resonance toward clear mouth placement.")
slider("resonance.forward_placement", "Forward placement", "resonance", 0.05, -1.0, 1.0, audible_impact="Moves sound toward a forward, immediate mask placement.")
slider("resonance.hollow_quality", "Hollow quality", "resonance", 0.0, 0.0, 1.0, audible_impact="Adds a controlled hollow or cavernous resonance.")
slider("resonance.ring", "Singer's ring", "resonance", 0.05, 0.0, 1.0, audible_impact="Adds a focused upper-mid resonance that improves projection.")
slider("resonance.low_body", "Low-frequency body", "resonance", 0.15, -1.0, 1.0, audible_impact="Adds or reduces low harmonic weight without simply changing loudness.")

# ---------------------------------------------------------------------------
# 3. Pitch and melody
# ---------------------------------------------------------------------------
slider("identity.pitch_range", "Pitch range", "pitch", 0.25, 0.0, 1.0, mode="studio", audible_impact="Moves from narrow/steady to broad/theatrical pitch motion.")
slider("pitch.melodic_variation", "Melodic variation", "pitch", 0.25, 0.0, 1.0, mode="studio", audible_impact="Increases the diversity of phrase contours.")
slider("pitch.movement_speed", "Pitch movement speed", "pitch", 0.0, -1.0, 1.0, audible_impact="Controls how rapidly pitch contours change.")
slider("pitch.contour_smoothness", "Contour smoothness", "pitch", 0.5, 0.0, 1.0, audible_impact="Moves from angular jumps to smooth transitions.")
slider("pitch.microprosody", "Microprosody", "pitch", 0.2, 0.0, 1.0, audible_impact="Adds small syllable-level pitch variation.")
slider("pitch.vibrato", "Vibrato", "pitch", 0.0, 0.0, 1.0, audible_impact="Adds periodic pitch modulation; narration-safe limits are enforced.")
slider("pitch.vibrato_rate", "Vibrato rate", "pitch", 0.35, 0.0, 1.0, audible_impact="Changes the speed of any enabled vibrato.")
slider("pitch.vibrato_depth", "Vibrato depth", "pitch", 0.0, 0.0, 1.0, audible_impact="Changes the width of any enabled vibrato.")
slider("pitch.phrase_arc", "Phrase arc", "pitch", 0.15, -1.0, 1.0, audible_impact="Shapes whether phrases rise, arch, or settle overall.")
slider("pitch.declination", "Pitch declination", "pitch", 0.15, -1.0, 1.0, audible_impact="Controls the natural downward tendency across a phrase.")
slider("pitch.reset_strength", "Pitch reset strength", "pitch", 0.25, 0.0, 1.0, audible_impact="Controls how much pitch resets at new sentences and paragraphs.")
slider("pitch.accent_height", "Pitch-accent height", "pitch", 0.25, 0.0, 1.0, audible_impact="Increases pitch prominence on emphasized words.")
slider("pitch.boundary_tone", "Boundary tone", "pitch", 0.0, -1.0, 1.0, audible_impact="Moves phrase endings from falling to rising.")
slider("pitch.ending_cadence", "Ending cadence", "pitch", -0.15, -1.0, 1.0, mode="studio", audible_impact="Controls assertive falling versus open rising sentence endings.")
slider("pitch.question_inflection", "Question inflection", "pitch", 0.35, -1.0, 1.0, mode="studio", audible_impact="Controls the degree and shape of question rises.")
slider("pitch.list_item_continuation", "List continuation contour", "pitch", 0.3, -1.0, 1.0, audible_impact="Keeps nonfinal list items perceptually open.")
slider("pitch.dialogue_variance", "Dialogue pitch variance", "pitch", 0.25, 0.0, 1.0, audible_impact="Adds extra pitch differentiation inside dialogue.")
slider("pitch.narrative_stability", "Narrative pitch stability", "pitch", 0.6, 0.0, 1.0, audible_impact="Higher values keep long-form narration centered across chapters.")
slider("pitch.emphasis_excursion", "Emphasis excursion", "pitch", 0.25, 0.0, 1.0, audible_impact="Changes how far emphasized syllables depart from the baseline.")
slider("pitch.random_drift", "Controlled pitch drift", "pitch", 0.02, 0.0, 1.0, audible_impact="Adds very slow variation; safety constraints keep identity stable.")

# ---------------------------------------------------------------------------
# 4. Timing and rhythm
# ---------------------------------------------------------------------------
slider("performance.speaking_rate", "Speaking rate", "timing", 1.0, 0.55, 1.65, 0.01, "x", mode="simple", audible_impact="Changes overall delivery speed while preserving intelligibility.")
slider("timing.sentence_rhythm", "Sentence rhythm", "timing", 0.15, -1.0, 1.0, mode="studio", audible_impact="Moves from even/measured to syncopated/varied sentence timing.")
slider("timing.phrase_length", "Phrase length", "timing", 0.0, -1.0, 1.0, mode="studio", audible_impact="Moves from short breath groups to longer connected phrases.")
slider("timing.pause_density", "Pause density", "timing", 0.2, 0.0, 1.0, mode="studio", audible_impact="Changes how frequently meaningful pauses occur.")
slider("timing.pause_duration", "Pause duration", "timing", 0.2, -1.0, 1.0, mode="studio", audible_impact="Changes average pause length without changing text.")
slider("timing.comma_pause", "Comma pause", "timing", 0.15, -1.0, 1.0, audible_impact="Changes pause behavior at commas.")
slider("timing.period_pause", "Period pause", "timing", 0.25, -1.0, 1.0, audible_impact="Changes pause behavior at full stops.")
slider("timing.semicolon_pause", "Semicolon pause", "timing", 0.2, -1.0, 1.0, audible_impact="Changes pause behavior at semicolons.")
slider("timing.colon_pause", "Colon pause", "timing", 0.2, -1.0, 1.0, audible_impact="Changes anticipatory pause behavior at colons.")
slider("timing.dash_pause", "Dash pause", "timing", 0.25, -1.0, 1.0, audible_impact="Changes interruption or aside timing around dashes.")
slider("timing.ellipsis_pause", "Ellipsis pause", "timing", 0.4, -1.0, 1.0, audible_impact="Changes suspended timing at ellipses.")
slider("timing.paragraph_reset", "Paragraph reset", "timing", 0.45, 0.0, 1.0, mode="studio", audible_impact="Controls the audible reset between paragraphs.")
slider("timing.chapter_reset", "Chapter reset", "timing", 0.7, 0.0, 1.0, audible_impact="Controls how strongly delivery resets at chapter boundaries.")
slider("timing.rubato", "Rubato", "timing", 0.1, 0.0, 1.0, audible_impact="Adds expressive local speeding and slowing.")
slider("timing.tempo_stability", "Tempo stability", "timing", 0.65, 0.0, 1.0, audible_impact="Higher values resist unintended rate drift across long passages.")
slider("timing.syllable_compression", "Syllable compression", "timing", 0.0, -1.0, 1.0, audible_impact="Changes how tightly unstressed syllables are packed.")
slider("timing.function_word_reduction", "Function-word timing reduction", "timing", 0.1, -1.0, 1.0, audible_impact="Speeds or preserves articles, prepositions, and other function words.")
slider("timing.pre_emphasis_pause", "Pre-emphasis pause", "timing", 0.05, 0.0, 1.0, audible_impact="Adds a small anticipatory pause before important words.")
slider("timing.post_emphasis_pause", "Post-emphasis pause", "timing", 0.05, 0.0, 1.0, audible_impact="Adds a small settling pause after important words.")
slider("timing.dialogue_turn_gap", "Dialogue-turn gap", "timing", 0.2, -1.0, 1.0, audible_impact="Changes spacing between alternating speakers or quoted turns.")
slider("timing.parenthetical_speed", "Parenthetical speed", "timing", 0.05, -1.0, 1.0, audible_impact="Changes the pace of asides and parenthetical material.")
slider("timing.footnote_speed", "Footnote speed", "timing", 0.0, -1.0, 1.0, audible_impact="Changes delivery speed for notes and footnotes.")
slider("timing.numeric_grouping", "Numeric grouping rhythm", "timing", 0.15, -1.0, 1.0, audible_impact="Controls grouping and pacing of long numbers.")

# ---------------------------------------------------------------------------
# 5. Articulation
# ---------------------------------------------------------------------------
slider("identity.articulation", "Articulation precision", "articulation", 0.25, -1.0, 1.0, mode="studio", audible_impact="Moves from soft/relaxed diction to highly precise diction.")
slider("articulation.consonant_sharpness", "Consonant sharpness", "articulation", 0.15, -1.0, 1.0, mode="studio", audible_impact="Changes the crispness of consonant edges.")
slider("articulation.vowel_definition", "Vowel definition", "articulation", 0.1, -1.0, 1.0, audible_impact="Changes the clarity and stability of vowel targets.")
slider("articulation.syllable_reduction", "Syllable reduction", "articulation", 0.05, -1.0, 1.0, mode="studio", audible_impact="Controls how strongly unstressed syllables are reduced.")
slider("articulation.linking", "Word linking", "articulation", 0.15, 0.0, 1.0, audible_impact="Increases connected-speech linking across word boundaries.")
slider("articulation.coarticulation", "Coarticulation", "articulation", 0.2, 0.0, 1.0, audible_impact="Controls how much neighboring sounds influence each other.")
slider("articulation.plosive_release", "Plosive release", "articulation", 0.0, -1.0, 1.0, audible_impact="Changes the release energy of p, t, k, b, d, and g.")
slider("articulation.fricative_energy", "Fricative energy", "articulation", 0.0, -1.0, 1.0, audible_impact="Changes the energy and clarity of fricative consonants.")
slider("articulation.sibilance", "Sibilance", "articulation", -0.05, -1.0, 1.0, audible_impact="Controls the prominence of sibilants before de-essing.")
slider("articulation.lateral_clarity", "Lateral clarity", "articulation", 0.0, -1.0, 1.0, audible_impact="Changes clarity of l-like sounds.")
slider("articulation.rhotic_clarity", "Rhotic clarity", "articulation", 0.1, -1.0, 1.0, audible_impact="Changes the definition of r-like sounds independently of accent rhoticity.")
slider("articulation.nasal_consonant_clarity", "Nasal consonant clarity", "articulation", 0.0, -1.0, 1.0, audible_impact="Changes definition of m, n, and ng sounds.")
slider("articulation.final_consonants", "Final-consonant retention", "articulation", 0.25, 0.0, 1.0, audible_impact="Controls how fully word-final consonants are retained.")
slider("articulation.cluster_simplification", "Cluster simplification", "articulation", 0.0, 0.0, 1.0, audible_impact="Allows controlled simplification of difficult consonant clusters.")
slider("articulation.schwa_strength", "Schwa strength", "articulation", 0.0, -1.0, 1.0, audible_impact="Changes the prominence of reduced central vowels.")
slider("articulation.vowel_length_contrast", "Vowel-length contrast", "articulation", 0.15, -1.0, 1.0, audible_impact="Changes timing contrast between short and long vowels.")
slider("articulation.diphthong_motion", "Diphthong motion", "articulation", 0.1, -1.0, 1.0, audible_impact="Changes how strongly vowels glide between targets.")
slider("articulation.enunciation_consistency", "Enunciation consistency", "articulation", 0.65, 0.0, 1.0, audible_impact="Higher values keep diction consistent over long passages.")
slider("articulation.proper_name_care", "Proper-name care", "articulation", 0.65, 0.0, 1.0, audible_impact="Increases deliberate handling of names after pronunciation rules are applied.")
slider("articulation.technical_term_care", "Technical-term care", "articulation", 0.6, 0.0, 1.0, audible_impact="Increases deliberate articulation of specialist vocabulary.")
slider("articulation.mumbled_quality", "Mumbled quality", "articulation", 0.0, 0.0, 1.0, audible_impact="Adds controlled mumbling; hard limits preserve intelligibility.")

# ---------------------------------------------------------------------------
# 6. Breath and texture
# ---------------------------------------------------------------------------
slider("identity.texture.breathiness", "Breathiness", "breath_texture", 0.08, 0.0, 1.0, mode="simple", audible_impact="Adds audible air to the vocal tone.")
slider("identity.texture.roughness", "Roughness", "breath_texture", 0.05, 0.0, 1.0, mode="studio", audible_impact="Adds controlled irregular/grainy texture.")
slider("identity.texture.rasp", "Rasp", "breath_texture", 0.02, 0.0, 1.0, mode="studio", audible_impact="Adds a dry, scraping edge distinct from general roughness.")
slider("identity.texture.airiness", "Airiness", "breath_texture", 0.08, 0.0, 1.0, mode="studio", audible_impact="Adds light, diffuse upper air around the tone.")
slider("identity.texture.gravel", "Gravel", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds low, coarse texture.")
slider("identity.texture.shimmer", "Shimmer", "breath_texture", 0.04, 0.0, 1.0, audible_impact="Adds subtle high-frequency liveliness.")
slider("breath.frequency", "Breath frequency", "breath_texture", 0.15, 0.0, 1.0, mode="studio", audible_impact="Changes how often natural breath events occur.")
slider("breath.audibility", "Breath audibility", "breath_texture", 0.1, 0.0, 1.0, mode="studio", audible_impact="Changes how prominent inhalations are.")
slider("breath.inhale_length", "Inhale length", "breath_texture", 0.0, -1.0, 1.0, audible_impact="Changes the duration of inserted inhalations.")
slider("breath.inhale_shape", "Inhale shape", "breath_texture", 0.0, -1.0, 1.0, audible_impact="Moves breath events from soft/rounded to quick/sharp.")
slider("breath.exhale_leak", "Phrase-end exhale", "breath_texture", 0.05, 0.0, 1.0, audible_impact="Adds controlled air release at phrase endings.")
slider("breath.catch_breath", "Catch-breath tendency", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds brief emotional catch breaths in high-intensity moments.")
slider("breath.sigh_tendency", "Sigh tendency", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds occasional sigh-like releases when context supports them.")
slider("texture.noise_floor", "Vocal noise floor", "breath_texture", 0.02, 0.0, 1.0, audible_impact="Adds a very low continuous texture component.")
slider("texture.jitter", "Pitch jitter", "breath_texture", 0.03, 0.0, 1.0, audible_impact="Adds tiny cycle-to-cycle pitch irregularity.")
slider("texture.shimmer_variation", "Amplitude shimmer", "breath_texture", 0.03, 0.0, 1.0, audible_impact="Adds tiny cycle-to-cycle amplitude irregularity.")
slider("texture.dryness", "Dryness", "breath_texture", 0.0, -1.0, 1.0, audible_impact="Moves from moist/smooth to dry/textured vocal quality.")
slider("texture.smokiness", "Smokiness", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds a dark, airy roughness blend.")
slider("texture.velvet", "Velvet quality", "breath_texture", 0.1, 0.0, 1.0, audible_impact="Adds smooth, soft harmonic density.")
slider("texture.metallic", "Metallic quality", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds a focused, metallic upper overtone color.")
slider("texture.age_instability", "Age-related instability", "breath_texture", 0.0, 0.0, 1.0, audible_impact="Adds controlled age-associated instability when perceived age is high.")
slider("texture.long_form_consistency", "Texture consistency", "breath_texture", 0.75, 0.0, 1.0, audible_impact="Higher values preserve texture across chapters.")

# ---------------------------------------------------------------------------
# 7. Emotion
# ---------------------------------------------------------------------------
slider("performance.energy", "Energy", "emotion", 0.1, -1.0, 1.0, mode="simple", audible_impact="Moves from subdued to highly energized delivery.")
slider("performance.expressiveness", "Expressiveness", "emotion", 0.25, 0.0, 1.0, mode="simple", audible_impact="Changes the breadth of emotional and prosodic variation.")
slider("performance.emotional_intensity", "Emotional intensity", "emotion", 0.15, 0.0, 1.0, mode="studio", audible_impact="Increases the strength of emotional signals without choosing one emotion.")
slider("performance.restraint", "Restraint", "emotion", 0.45, 0.0, 1.0, mode="studio", audible_impact="Higher values contain emotional display and reduce overacting.")
slider("performance.confidence", "Confidence", "emotion", 0.25, -1.0, 1.0, mode="studio", audible_impact="Moves from hesitant to assured delivery.")
slider("performance.intimacy", "Intimacy", "emotion", 0.2, -1.0, 1.0, mode="simple", audible_impact="Moves from public/distant to close and confiding.")
slider("performance.authority", "Authority", "emotion", 0.2, -1.0, 1.0, mode="simple", audible_impact="Moves from deferential to commanding.")
slider("performance.friendliness", "Friendliness", "emotion", 0.2, -1.0, 1.0, mode="studio", audible_impact="Moves from cool/neutral to warmly approachable.")
slider("performance.suspense", "Suspense", "emotion", 0.0, 0.0, 1.0, mode="studio", audible_impact="Adds held timing, controlled tension, and anticipatory emphasis.")
slider("performance.humor", "Humor", "emotion", 0.0, 0.0, 1.0, mode="studio", audible_impact="Adds comic timing and lightness without changing text.")
slider("performance.sadness", "Sadness", "emotion", 0.0, 0.0, 1.0, mode="studio", audible_impact="Adds subdued energy, slower contours, and weighted endings.")
slider("performance.excitement", "Excitement", "emotion", 0.0, 0.0, 1.0, mode="studio", audible_impact="Adds brighter, faster, more dynamic delivery.")
slider("performance.urgency", "Urgency", "emotion", 0.0, 0.0, 1.0, mode="studio", audible_impact="Adds forward momentum and reduced hesitation.")
slider("performance.conversationality", "Conversationality", "emotion", 0.35, 0.0, 1.0, mode="studio", audible_impact="Moves from formal reading to natural conversational delivery.")
slider("performance.theatricality", "Theatricality", "emotion", 0.05, 0.0, 1.0, mode="studio", audible_impact="Increases stage-like projection and dramatic contrast.")
slider("emotion.joy", "Joy", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds positive valence, lift, and energetic warmth.")
slider("emotion.anger", "Anger", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds controlled force, compression, and sharper attacks.")
slider("emotion.fear", "Fear", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds tension, instability, and breath behavior appropriate to fear.")
slider("emotion.disgust", "Disgust", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds aversive coloring and compressed emphasis.")
slider("emotion.surprise", "Surprise", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds rapid pitch/energy change and widened emphasis.")
slider("emotion.tenderness", "Tenderness", "emotion", 0.05, 0.0, 1.0, audible_impact="Adds gentle onset, warmth, and close phrasing.")
slider("emotion.awe", "Awe", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds spacious pacing and elevated melodic contour.")
slider("emotion.calm", "Calm", "emotion", 0.2, 0.0, 1.0, audible_impact="Adds steady timing, controlled energy, and smooth contours.")
slider("emotion.irony", "Irony", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds subtle contrast between wording and delivery.")
slider("emotion.sarcasm", "Sarcasm", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds marked ironic emphasis; constrained to avoid caricature.")
slider("emotion.curiosity", "Curiosity", "emotion", 0.05, 0.0, 1.0, audible_impact="Adds exploratory phrasing and open contours.")
slider("emotion.reassurance", "Reassurance", "emotion", 0.1, 0.0, 1.0, audible_impact="Adds steadiness, warmth, and confidence.")
slider("emotion.solemnity", "Solemnity", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds weight, slower cadence, and reduced playfulness.")
slider("emotion.optimism", "Optimism", "emotion", 0.05, 0.0, 1.0, audible_impact="Adds positive lift without overt excitement.")
slider("emotion.melancholy", "Melancholy", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds reflective sadness with restrained energy.")
slider("emotion.embarrassment", "Embarrassment", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds hesitation, reduced projection, and self-conscious timing.")
slider("emotion.pride", "Pride", "emotion", 0.0, 0.0, 1.0, audible_impact="Adds upright authority and measured emphasis.")
slider("emotion.empathy", "Empathy", "emotion", 0.15, 0.0, 1.0, audible_impact="Adds responsive warmth and listener-oriented pacing.")
slider("emotion.volatility", "Emotional volatility", "emotion", 0.1, 0.0, 1.0, audible_impact="Controls how quickly emotional state changes within a passage.")
slider("emotion.recovery_speed", "Emotional recovery", "emotion", 0.5, 0.0, 1.0, audible_impact="Controls how quickly delivery returns toward baseline after peaks.")
slider("emotion.context_sensitivity", "Context sensitivity", "emotion", 0.65, 0.0, 1.0, audible_impact="Higher values let punctuation and semantics guide affect more strongly.")

# ---------------------------------------------------------------------------
# 8. Accent and phonology
# ---------------------------------------------------------------------------
select("accent.locale", "Language/locale", "accent", "en-US", ["en-US", "en-GB", "en-AU", "en-CA", "en-IN", "en-IE", "en-NZ", "en-ZA"], mode="simple", description="Primary pronunciation locale used to select a compatible provider voice.")
select("accent.region", "Regional influence", "accent", "general", ["general", "mid-atlantic", "new-england", "southern-us", "western-us", "received-pronunciation", "estuary", "northern-england", "scottish", "irish", "australian-general", "indian-general"], mode="studio", description="A bounded regional influence; the mapper avoids exaggerated caricature.")
slider("accent.strength", "Accent strength", "accent", 0.1, 0.0, 1.0, mode="simple", audible_impact="Controls how strongly the selected regional influence appears.")
slider("accent.rhoticity", "Rhoticity", "accent", 0.5, 0.0, 1.0, mode="studio", audible_impact="Controls whether post-vocalic r sounds are retained.")
slider("accent.vowel_placement", "Vowel placement", "accent", 0.0, -1.0, 1.0, mode="studio", audible_impact="Moves vowel targets along a constrained regional placement continuum.")
slider("accent.consonant_sharpness", "Accent consonant sharpness", "accent", 0.0, -1.0, 1.0, mode="studio", audible_impact="Changes region-linked consonant definition.")
slider("accent.syllable_reduction", "Accent syllable reduction", "accent", 0.0, -1.0, 1.0, mode="studio", audible_impact="Changes region-linked unstressed-syllable reduction.")
slider("accent.formality", "Formality", "accent", 0.2, -1.0, 1.0, mode="studio", audible_impact="Moves speech behavior from casual to formal.")
slider("accent.code_switching", "Code-switching tendency", "accent", 0.0, 0.0, 1.0, mode="studio", audible_impact="Controls switching behavior only when language spans are explicitly marked.")
slider("accent.foreign_word_fidelity", "Foreign-word fidelity", "accent", 0.6, 0.0, 1.0, mode="studio", audible_impact="Controls how strongly foreign words retain source-language pronunciation.")
slider("accent.t_flapping", "T/D flapping", "accent", 0.4, 0.0, 1.0, audible_impact="Controls flapped t/d behavior in eligible environments.")
slider("accent.t_glottalization", "T glottalization", "accent", 0.05, 0.0, 1.0, audible_impact="Controls glottal replacement of t in eligible environments.")
slider("accent.yod_dropping", "Yod dropping", "accent", 0.2, 0.0, 1.0, audible_impact="Controls yod retention in words such as new or tune.")
slider("accent.h_dropping", "H dropping", "accent", 0.0, 0.0, 1.0, audible_impact="Controls h-dropping; capped to prevent caricature and loss of clarity.")
slider("accent.l_vocalization", "L vocalization", "accent", 0.05, 0.0, 1.0, audible_impact="Controls vocalized dark-l behavior.")
slider("accent.th_fronting", "TH fronting", "accent", 0.0, 0.0, 1.0, audible_impact="Controls constrained th-fronting behavior.")
slider("accent.vowel_length", "Regional vowel length", "accent", 0.0, -1.0, 1.0, audible_impact="Changes regional vowel-duration patterns.")
slider("accent.trap_bath_split", "TRAP-BATH split", "accent", 0.0, 0.0, 1.0, audible_impact="Controls the bounded TRAP-BATH distinction where supported.")
slider("accent.lot_cloth_split", "LOT-CLOTH split", "accent", 0.0, 0.0, 1.0, audible_impact="Controls the bounded LOT-CLOTH distinction where supported.")
slider("accent.cot_caught_merge", "COT-CAUGHT merger", "accent", 0.5, 0.0, 1.0, audible_impact="Controls the degree of COT-CAUGHT merger.")
slider("accent.pin_pen_merge", "PIN-PEN merger", "accent", 0.0, 0.0, 1.0, audible_impact="Controls the degree of PIN-PEN merger.")
slider("accent.canadian_raising", "Canadian raising", "accent", 0.0, 0.0, 1.0, audible_impact="Controls raising of eligible diphthongs.")
slider("accent.intrusive_r", "Linking/intrusive R", "accent", 0.0, 0.0, 1.0, audible_impact="Controls linking or intrusive r behavior in non-rhotic styles.")
slider("accent.schwa_insertion", "Schwa insertion", "accent", 0.0, 0.0, 1.0, audible_impact="Controls epenthetic schwa in difficult clusters.")
slider("accent.prosodic_transfer", "Prosodic transfer", "accent", 0.0, 0.0, 1.0, audible_impact="Adds constrained first-language rhythm influence for multilingual speech.")
slider("accent.consistency", "Accent consistency", "accent", 0.8, 0.0, 1.0, audible_impact="Higher values resist unintended accent drift across chapters.")

# ---------------------------------------------------------------------------
# 9. Narration behavior
# ---------------------------------------------------------------------------
slider("narration.emphasis_strength", "Emphasis strength", "narration", 0.2, 0.0, 1.0, mode="studio", audible_impact="Changes prominence assigned to semantically important words.")
slider("narration.dialogue_lift", "Dialogue lift", "narration", 0.2, -1.0, 1.0, mode="studio", audible_impact="Makes quoted dialogue more distinct from narrative prose.")
slider("narration.dialogue_characterization", "Dialogue characterization", "narration", 0.15, 0.0, 1.0, audible_impact="Changes character differentiation while retaining narrator identity.")
slider("narration.dialogue_attribution_deemphasis", "Dialogue-tag de-emphasis", "narration", 0.25, 0.0, 1.0, audible_impact="Reduces prominence of he said/she said style attributions.")
slider("narration.quotation_boundary", "Quotation boundary", "narration", 0.25, 0.0, 1.0, audible_impact="Adds subtle entry/exit cues around quotations.")
slider("narration.internal_monologue", "Internal-monologue intimacy", "narration", 0.25, 0.0, 1.0, audible_impact="Makes internal thought closer and more private.")
slider("narration.scene_transition", "Scene-transition reset", "narration", 0.45, 0.0, 1.0, audible_impact="Controls audible reset at scene breaks.")
slider("narration.heading_distinction", "Heading distinction", "narration", 0.45, 0.0, 1.0, audible_impact="Makes headings distinct without sounding announced mechanically.")
slider("narration.list_structure", "List structure", "narration", 0.5, 0.0, 1.0, audible_impact="Clarifies list item boundaries and finality.")
slider("narration.parenthetical_aside", "Parenthetical aside", "narration", 0.3, 0.0, 1.0, audible_impact="Makes parenthetical material sound secondary but intelligible.")
slider("narration.footnote_separation", "Footnote separation", "narration", 0.45, 0.0, 1.0, audible_impact="Separates notes from body narration.")
slider("narration.definition_mode", "Definition mode", "narration", 0.3, 0.0, 1.0, audible_impact="Clarifies term-definition structures in technical nonfiction.")
slider("narration.legal_precision", "Legal precision", "narration", 0.4, 0.0, 1.0, audible_impact="Prioritizes unambiguous pacing for legal material.")
slider("narration.technical_precision", "Technical precision", "narration", 0.4, 0.0, 1.0, audible_impact="Prioritizes clarity for formulas, versions, and technical terms.")
slider("narration.children_storytelling", "Children's storytelling", "narration", 0.0, 0.0, 1.0, audible_impact="Adds friendly variation and clarity suitable for children's narration.")
slider("narration.advertising_punch", "Advertising punch", "narration", 0.0, 0.0, 1.0, audible_impact="Adds concise energy and product-focused emphasis.")
slider("narration.memoir_intimacy", "Memoir intimacy", "narration", 0.0, 0.0, 1.0, audible_impact="Adds reflective closeness appropriate to memoir.")
slider("narration.nonfiction_objectivity", "Nonfiction objectivity", "narration", 0.35, 0.0, 1.0, audible_impact="Adds measured neutrality while preserving engagement.")
slider("narration.fiction_immersion", "Fiction immersion", "narration", 0.25, 0.0, 1.0, audible_impact="Increases scene-responsive performance without losing narrator continuity.")
slider("narration.suspense_pacing", "Suspense pacing", "narration", 0.0, 0.0, 1.0, audible_impact="Coordinates pauses, rate, and emphasis for suspense passages.")
slider("narration.comedic_timing", "Comedic timing", "narration", 0.0, 0.0, 1.0, audible_impact="Coordinates pauses and de-emphasis for jokes and reversals.")
slider("narration.poetry_lineation", "Poetry lineation", "narration", 0.25, 0.0, 1.0, audible_impact="Controls sensitivity to line breaks and stanza form.")
slider("narration.stage_direction_handling", "Stage-direction handling", "narration", 0.2, 0.0, 1.0, audible_impact="Separates stage directions from spoken dialogue.")
slider("narration.long_form_identity_lock", "Long-form identity lock", "narration", 0.85, 0.0, 1.0, mode="studio", audible_impact="Higher values prioritize stable identity over local expressiveness.")
slider("narration.chapter_memory", "Chapter-to-chapter continuity", "narration", 0.8, 0.0, 1.0, audible_impact="Maintains timbre and performance baseline between chapter jobs.")
slider("narration.dynamic_range", "Narrative dynamic range", "narration", 0.35, 0.0, 1.0, audible_impact="Controls the difference between quiet and intense moments.")

# ---------------------------------------------------------------------------
# 10. Recording environment
# ---------------------------------------------------------------------------
select("environment.microphone_model", "Virtual microphone", "environment", "neutral-condenser", ["neutral-condenser", "warm-condenser", "broadcast-dynamic", "ribbon-soft", "close-lavalier", "transparent"], mode="studio")
slider("environment.mic_distance", "Microphone distance", "environment", 0.25, 0.0, 1.0, mode="studio", audible_impact="Moves from close/intimate to more distant capture.")
slider("environment.proximity_effect", "Proximity effect", "environment", 0.1, 0.0, 1.0, mode="studio", audible_impact="Adds low-frequency intimacy associated with close microphones.")
slider("environment.off_axis", "Off-axis angle", "environment", 0.05, 0.0, 1.0, audible_impact="Softens presence and sibilance as the virtual microphone moves off axis.")
slider("environment.room_size", "Room size", "environment", 0.05, 0.0, 1.0, mode="studio", audible_impact="Moves from dry booth to larger acoustic space.")
slider("environment.room_liveness", "Room liveness", "environment", 0.03, 0.0, 1.0, mode="studio", audible_impact="Changes early reflections and decay without compromising audiobook clarity.")
slider("environment.early_reflections", "Early reflections", "environment", 0.03, 0.0, 1.0, audible_impact="Adds near-field room cues.")
slider("environment.reverb_decay", "Reverb decay", "environment", 0.02, 0.0, 1.0, audible_impact="Changes the tail length of the virtual space.")
slider("environment.stereo_width", "Stereo width", "environment", 0.0, 0.0, 1.0, audible_impact="Adds controlled spatial width; narration defaults remain centered.")
slider("environment.room_tone", "Room tone", "environment", 0.02, 0.0, 1.0, audible_impact="Adds subtle continuous ambience for continuity.")
slider("environment.noise_character", "Environmental noise character", "environment", 0.0, 0.0, 1.0, audible_impact="Adds bounded studio texture; production exports default near zero.")
slider("environment.absorption", "Room absorption", "environment", 0.85, 0.0, 1.0, audible_impact="Higher values create a drier, more treated room.")
slider("environment.floor_reflection", "Floor reflection", "environment", 0.0, 0.0, 1.0, audible_impact="Adds a subtle floor-boundary reflection.")
slider("environment.listener_distance", "Listener distance", "environment", 0.15, 0.0, 1.0, audible_impact="Changes perceived interpersonal distance independently of mic distance.")
slider("environment.head_turn", "Head-turn variation", "environment", 0.0, 0.0, 1.0, audible_impact="Adds subtle spatial motion during expressive moments.")

# ---------------------------------------------------------------------------
# 11. Post-processing
# ---------------------------------------------------------------------------
slider("post.target_loudness", "Target loudness", "post", -20.0, -24.0, -14.0, 0.1, "dBFS", mode="studio", audible_impact="Sets the finishing loudness target; downstream QC still decides compliance.")
slider("post.peak_ceiling", "Peak ceiling", "post", -3.0, -6.0, -1.0, 0.1, "dBFS", mode="studio", audible_impact="Limits maximum peaks before export.")
slider("post.compression", "Compression", "post", 0.2, 0.0, 1.0, mode="studio", audible_impact="Reduces dynamic variation to improve consistency.")
slider("post.compression_attack", "Compressor attack", "post", 0.35, 0.0, 1.0, audible_impact="Controls how quickly compression responds.")
slider("post.compression_release", "Compressor release", "post", 0.45, 0.0, 1.0, audible_impact="Controls how quickly compression relaxes.")
slider("post.de_esser", "De-essing", "post", 0.2, 0.0, 1.0, mode="studio", audible_impact="Reduces harsh sibilants while preserving diction.")
slider("post.low_cut", "Low-cut filter", "post", 0.15, 0.0, 1.0, audible_impact="Reduces rumble and excessive sub-bass.")
slider("post.low_shelf", "Low shelf", "post", 0.0, -1.0, 1.0, audible_impact="Adjusts bass weight after synthesis.")
slider("post.presence_eq", "Presence EQ", "post", 0.05, -1.0, 1.0, audible_impact="Adjusts midrange intelligibility and closeness.")
slider("post.air_eq", "Air EQ", "post", 0.0, -1.0, 1.0, audible_impact="Adjusts upper-frequency openness.")
slider("post.harshness_control", "Harshness control", "post", 0.15, 0.0, 1.0, audible_impact="Reduces fatiguing upper-mid energy.")
slider("post.saturation", "Saturation", "post", 0.03, 0.0, 1.0, audible_impact="Adds gentle harmonic density.")
slider("post.transient_softening", "Transient softening", "post", 0.05, 0.0, 1.0, audible_impact="Rounds overly sharp consonant transients.")
slider("post.noise_reduction", "Noise reduction", "post", 0.2, 0.0, 1.0, audible_impact="Reduces synthetic or environmental noise while avoiding artifacts.")
slider("post.gate_strength", "Gate strength", "post", 0.05, 0.0, 1.0, audible_impact="Controls low-level attenuation between phrases.")
slider("post.limiter", "Limiter strength", "post", 0.2, 0.0, 1.0, audible_impact="Controls final peak limiting.")
slider("post.mono_compatibility", "Mono compatibility", "post", 1.0, 0.0, 1.0, audible_impact="Higher values preserve centered, mono-safe audiobook output.")
slider("post.chapter_match", "Chapter loudness matching", "post", 0.9, 0.0, 1.0, mode="studio", audible_impact="Higher values prioritize consistent loudness between chapters.")
slider("post.timbre_match", "Chapter timbre matching", "post", 0.8, 0.0, 1.0, audible_impact="Higher values reduce chapter-to-chapter tonal drift.")
slider("post.breath_control", "Breath level control", "post", 0.2, 0.0, 1.0, audible_impact="Balances breath realism against distraction.")

# ---------------------------------------------------------------------------
# 12. Text interpretation
# ---------------------------------------------------------------------------
select("interpretation.number_style", "Number reading", "interpretation", "contextual", ["contextual", "cardinal", "digit-by-digit", "year-aware", "telephone-aware"], mode="studio")
select("interpretation.date_style", "Date reading", "interpretation", "locale", ["locale", "month-first", "day-first", "iso-literal"], mode="studio")
select("interpretation.acronym_style", "Acronym handling", "interpretation", "auto", ["auto", "spell", "word", "dictionary-only"], mode="studio")
select("interpretation.initialism_style", "Initialism handling", "interpretation", "spell", ["spell", "word", "auto"], mode="studio")
select("interpretation.url_style", "URL reading", "interpretation", "natural", ["natural", "literal", "domain-only", "omit-protocol"], mode="studio")
select("interpretation.email_style", "Email reading", "interpretation", "natural", ["natural", "literal", "compact"], mode="studio")
select("interpretation.currency_style", "Currency reading", "interpretation", "contextual", ["contextual", "full", "symbol-first"], mode="studio")
select("interpretation.fraction_style", "Fraction reading", "interpretation", "natural", ["natural", "numerator-denominator", "decimal"], mode="studio")
select("interpretation.roman_numeral_style", "Roman numeral reading", "interpretation", "contextual", ["contextual", "ordinal", "cardinal", "letters"], mode="studio")
select("interpretation.symbol_style", "Symbol reading", "interpretation", "contextual", ["contextual", "literal", "minimal"], mode="studio")
select("interpretation.citation_style", "Citation reading", "interpretation", "compact", ["compact", "full", "skip-brackets"], mode="studio")
select("interpretation.footnote_style", "Footnote reading", "interpretation", "separate", ["separate", "inline", "end-of-chapter", "skip"], mode="studio")
select("interpretation.abbreviation_style", "Abbreviation handling", "interpretation", "expand-known", ["expand-known", "literal", "dictionary-only"], mode="studio")
slider("interpretation.semantic_emphasis", "Semantic emphasis", "interpretation", 0.4, 0.0, 1.0, mode="studio", audible_impact="Controls how strongly language analysis drives emphasis.")
slider("interpretation.punctuation_sensitivity", "Punctuation sensitivity", "interpretation", 0.65, 0.0, 1.0, mode="studio", audible_impact="Controls how strongly punctuation affects timing and contour.")
slider("interpretation.syntax_sensitivity", "Syntax sensitivity", "interpretation", 0.55, 0.0, 1.0, audible_impact="Controls how strongly clause structure shapes phrasing.")
slider("interpretation.discourse_sensitivity", "Discourse sensitivity", "interpretation", 0.5, 0.0, 1.0, audible_impact="Controls how strongly topic structure shapes resets and emphasis.")
slider("interpretation.negation_emphasis", "Negation emphasis", "interpretation", 0.25, 0.0, 1.0, audible_impact="Controls prominence of negative operators such as not and never.")
slider("interpretation.contrast_emphasis", "Contrast emphasis", "interpretation", 0.35, 0.0, 1.0, audible_impact="Controls prominence of contrastive words and constructions.")
slider("interpretation.new_information_emphasis", "New-information emphasis", "interpretation", 0.3, 0.0, 1.0, audible_impact="Controls prominence of newly introduced concepts.")
slider("interpretation.given_information_deemphasis", "Given-information de-emphasis", "interpretation", 0.25, 0.0, 1.0, audible_impact="Reduces prominence of repeated or already established information.")
slider("interpretation.quotation_sensitivity", "Quotation sensitivity", "interpretation", 0.55, 0.0, 1.0, audible_impact="Controls how strongly quotation marks alter delivery.")
slider("interpretation.markdown_sensitivity", "Markup sensitivity", "interpretation", 0.6, 0.0, 1.0, audible_impact="Controls interpretation of headings, emphasis, and lists in structured text.")
slider("interpretation.pronunciation_rule_strength", "Pronunciation-rule strength", "interpretation", 1.0, 0.0, 1.0, mode="studio", audible_impact="Controls application of the saved pronunciation dictionary.")
slider("interpretation.ambiguity_caution", "Ambiguity caution", "interpretation", 0.65, 0.0, 1.0, audible_impact="Higher values favor conservative readings of ambiguous tokens.")
slider("interpretation.proper_name_pause", "Proper-name preparation", "interpretation", 0.1, 0.0, 1.0, audible_impact="Adds subtle timing preparation around difficult names.")
slider("interpretation.math_expression_care", "Math-expression care", "interpretation", 0.6, 0.0, 1.0, audible_impact="Increases deliberate handling of mathematical expressions.")
slider("interpretation.code_expression_care", "Code-expression care", "interpretation", 0.6, 0.0, 1.0, audible_impact="Increases deliberate handling of code and identifiers.")
toggle("interpretation.preserve_unknown_tokens", "Preserve unknown tokens", "interpretation", True, mode="studio", description="Prevents silent rewriting of unknown names, symbols, or identifiers.")
toggle("interpretation.require_explicit_language_spans", "Require explicit language spans", "interpretation", True, mode="studio", description="Prevents uncontrolled code switching when language is not explicitly marked.")
toggle("interpretation.expand_common_abbreviations", "Expand common abbreviations", "interpretation", True, mode="studio")
toggle("interpretation.read_alt_text", "Read image alt text", "interpretation", False, description="Allows accessible alt text to be narrated when the source pipeline marks it as intended content.")

CONTROL_BY_PATH = {control.path: control for control in _CONTROLS}
if len(CONTROL_BY_PATH) != len(_CONTROLS):
    raise RuntimeError("Voice City parameter schema contains duplicate paths")

# The source specification describes Studio as approximately fifty controls.
# A number of controls are authored with ``mode="studio"`` because they are
# conceptually approachable, but this curated set keeps the default Studio
# surface intentionally bounded.  Every remaining control is still available
# in Laboratory and can be found by search.
_STUDIO_EXTRA_PATHS = {
    "source.fold_closure",
    "source.vocal_effort",
    "source.breath_support",
    "identity.body_size",
    "identity.presence",
    "identity.timbre_complexity",
    "identity.resonance.chest",
    "identity.resonance.mouth",
    "identity.resonance.nasal",
    "identity.resonance.head",
    "identity.pitch_range",
    "pitch.melodic_variation",
    "pitch.ending_cadence",
    "pitch.question_inflection",
    "timing.sentence_rhythm",
    "timing.phrase_length",
    "timing.pause_density",
    "timing.pause_duration",
    "timing.paragraph_reset",
    "identity.articulation",
    "articulation.consonant_sharpness",
    "articulation.syllable_reduction",
    "identity.texture.roughness",
    "identity.texture.airiness",
    "breath.frequency",
    "breath.audibility",
    "performance.emotional_intensity",
    "performance.restraint",
    "performance.confidence",
    "performance.conversationality",
    "accent.region",
    "accent.rhoticity",
    "accent.vowel_placement",
    "accent.formality",
    "narration.emphasis_strength",
    "narration.dialogue_lift",
    "environment.microphone_model",
    "post.target_loudness",
    "interpretation.number_style",
    "interpretation.date_style",
    "interpretation.acronym_style",
    "interpretation.pronunciation_rule_strength",
}


def _effective_mode(control: ControlDefinition) -> str:
    if control.mode == "simple":
        return "simple"
    if control.path in _STUDIO_EXTRA_PATHS:
        return "studio"
    return "laboratory"

# Stable aliases used by natural-language generation and mutation.
ALIAS_TO_PATH: dict[str, str] = {}
for _control in _CONTROLS:
    ALIAS_TO_PATH[_control.label.lower()] = _control.path
    ALIAS_TO_PATH[_control.path.split(".")[-1].replace("_", " ")] = _control.path
    for _alias in _control.aliases:
        ALIAS_TO_PATH[_alias.lower()] = _control.path


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    cursor = document
    parts = path.split(".")
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = value


def get_path(document: Mapping[str, Any], path: str, default: Any = None) -> Any:
    cursor: Any = document
    for part in path.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _flatten(document: Mapping[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            yield from _flatten(value, path)
        else:
            yield path, value


def default_parameters(seed: int = 481928) -> dict[str, Any]:
    document: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "seed": int(seed)}
    for control in _CONTROLS:
        _set_path(document, control.path, copy.deepcopy(control.default))
    return document


def _validate_control_value(control: ControlDefinition, value: Any, warnings: list[str]) -> Any:
    if control.control_type == "slider":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ParameterValidationError(f"{control.path} must be a finite number")
        numeric = float(value)
        assert control.minimum is not None and control.maximum is not None
        clamped = max(control.minimum, min(control.maximum, numeric))
        if clamped != numeric:
            warnings.append(f"{control.path} was constrained to {clamped:g}")
        return round(clamped, 6)
    if control.control_type == "select":
        if not isinstance(value, str) or value not in control.options:
            raise ParameterValidationError(
                f"{control.path} must be one of: {', '.join(control.options)}"
            )
        return value
    if control.control_type == "toggle":
        if not isinstance(value, bool):
            raise ParameterValidationError(f"{control.path} must be true or false")
        return value
    raise ParameterValidationError(f"Unsupported control type: {control.control_type}")


def _normalize_resonance(document: dict[str, Any], warnings: list[str]) -> None:
    paths = [
        "identity.resonance.chest",
        "identity.resonance.throat",
        "identity.resonance.mouth",
        "identity.resonance.nasal",
        "identity.resonance.head",
    ]
    values = [float(get_path(document, path, 0.0)) for path in paths]
    total = sum(values)
    if total <= 0.000001:
        values = [0.25, 0.15, 0.4, 0.05, 0.15]
        total = 1.0
        warnings.append("Resonance weights were reset because all placements were zero")
    normalized = [round(value / total, 6) for value in values]
    # Correct rounding so the stored vector sums exactly to 1.0.
    normalized[2] = round(normalized[2] + (1.0 - sum(normalized)), 6)
    for path, value in zip(paths, normalized):
        _set_path(document, path, value)
    if abs(total - 1.0) > 0.0001:
        warnings.append("Resonance weights were normalized to sum to 1.0")


def _apply_cross_control_constraints(document: dict[str, Any], warnings: list[str]) -> None:
    breathiness = float(get_path(document, "identity.texture.breathiness", 0.0))
    effort = float(get_path(document, "source.vocal_effort", 0.0))
    closure = float(get_path(document, "source.fold_closure", 0.0))
    roughness = float(get_path(document, "identity.texture.roughness", 0.0))
    rasp = float(get_path(document, "identity.texture.rasp", 0.0))
    gravel = float(get_path(document, "identity.texture.gravel", 0.0))
    pitch = abs(float(get_path(document, "identity.pitch_center", 0.0)))
    mumble = float(get_path(document, "articulation.mumbled_quality", 0.0))
    precision = float(get_path(document, "identity.articulation", 0.0))
    h_drop = float(get_path(document, "accent.h_dropping", 0.0))
    th_front = float(get_path(document, "accent.th_fronting", 0.0))

    # Airy voices should not simultaneously be maximally pressed.  Preserve the
    # user's requested direction while constraining the unstable combination.
    if breathiness > 0.75 and (effort > 0.65 or closure > 0.7):
        _set_path(document, "source.vocal_effort", min(effort, 0.55))
        _set_path(document, "source.fold_closure", min(closure, 0.6))
        warnings.append("High breathiness constrained vocal effort/closure to a stable combination")

    texture_sum = roughness + rasp + gravel
    if texture_sum > 1.75:
        scale = 1.75 / texture_sum
        _set_path(document, "identity.texture.roughness", round(roughness * scale, 6))
        _set_path(document, "identity.texture.rasp", round(rasp * scale, 6))
        _set_path(document, "identity.texture.gravel", round(gravel * scale, 6))
        warnings.append("Combined roughness, rasp, and gravel were constrained to preserve intelligibility")

    if pitch > 0.8 and gravel > 0.65:
        _set_path(document, "identity.texture.gravel", 0.65)
        warnings.append("Extreme pitch/gravel combination was constrained")

    if mumble > 0.55:
        _set_path(document, "articulation.mumbled_quality", 0.55)
        if precision < -0.4:
            _set_path(document, "identity.articulation", -0.4)
        warnings.append("Mumbled quality was limited to preserve narration intelligibility")

    if h_drop + th_front > 1.1:
        scale = 1.1 / (h_drop + th_front)
        _set_path(document, "accent.h_dropping", round(h_drop * scale, 6))
        _set_path(document, "accent.th_fronting", round(th_front * scale, 6))
        warnings.append("Combined accent transformations were constrained to prevent caricature")

    accent_strength = float(get_path(document, "accent.strength", 0.0))
    accent_consistency = float(get_path(document, "accent.consistency", 0.8))
    if accent_strength > 0.75 and accent_consistency < 0.5:
        _set_path(document, "accent.consistency", 0.5)
        warnings.append("Strong accents require a minimum consistency setting")

    vibrato = float(get_path(document, "pitch.vibrato", 0.0))
    vibrato_depth = float(get_path(document, "pitch.vibrato_depth", 0.0))
    if vibrato * vibrato_depth > 0.18:
        _set_path(document, "pitch.vibrato_depth", round(0.18 / max(vibrato, 0.0001), 6))
        warnings.append("Vibrato depth was limited for spoken narration")

    emotional_paths = [
        path for path in CONTROL_BY_PATH
        if path.startswith("emotion.") and path not in {
            "emotion.context_sensitivity", "emotion.recovery_speed", "emotion.volatility"
        }
    ]
    emotional_values = [float(get_path(document, path, 0.0)) for path in emotional_paths]
    emotional_total = sum(emotional_values)
    if emotional_total > 6.0:
        scale = 6.0 / emotional_total
        for path, value in zip(emotional_paths, emotional_values):
            _set_path(document, path, round(value * scale, 6))
        warnings.append("Simultaneous emotion weights were normalized to avoid an unstable blend")

    if float(get_path(document, "environment.room_liveness", 0.0)) > 0.45:
        _set_path(document, "environment.room_liveness", 0.45)
        warnings.append("Room liveness was limited for audiobook intelligibility")
    if float(get_path(document, "environment.reverb_decay", 0.0)) > 0.35:
        _set_path(document, "environment.reverb_decay", 0.35)
        warnings.append("Reverb decay was limited for audiobook intelligibility")


def normalize_parameters(
    parameters: Mapping[str, Any] | None,
    *,
    seed: int | None = None,
    reject_unknown: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Return an immutable-ready canonical document and human-readable warnings.

    ``parameters`` may be a full canonical document or a sparse nested patch.
    Unknown paths are rejected by default so future-version data is never
    silently misinterpreted.
    """
    incoming = copy.deepcopy(dict(parameters or {}))
    incoming_schema = incoming.pop("schema_version", SCHEMA_VERSION)
    incoming_seed = incoming.pop("seed", seed if seed is not None else 481928)
    if incoming_schema != SCHEMA_VERSION:
        raise ParameterValidationError(
            f"Unsupported Voice City schema_version {incoming_schema!r}; expected {SCHEMA_VERSION!r}"
        )
    if isinstance(incoming_seed, bool) or not isinstance(incoming_seed, int):
        raise ParameterValidationError("seed must be an integer")
    canonical_seed = int(incoming_seed) % 2147483647

    flattened = dict(_flatten(incoming))
    unknown = sorted(path for path in flattened if path not in CONTROL_BY_PATH)
    if unknown and reject_unknown:
        raise ParameterValidationError(f"Unknown Voice City parameter path(s): {', '.join(unknown[:12])}")

    document = default_parameters(canonical_seed)
    warnings: list[str] = []
    for path, value in flattened.items():
        control = CONTROL_BY_PATH.get(path)
        if not control:
            continue
        _set_path(document, path, _validate_control_value(control, value, warnings))

    _normalize_resonance(document, warnings)
    _apply_cross_control_constraints(document, warnings)
    document["schema_version"] = SCHEMA_VERSION
    document["seed"] = canonical_seed
    return document, warnings


def merge_parameter_patch(
    base: Mapping[str, Any], patch: Mapping[str, Any], *, seed: int | None = None
) -> tuple[dict[str, Any], list[str]]:
    merged = copy.deepcopy(dict(base))
    for path, value in _flatten(patch):
        if path in {"schema_version", "seed"}:
            continue
        _set_path(merged, path, value)
    if seed is not None:
        merged["seed"] = seed
    return normalize_parameters(merged)


def canonical_json(parameters: Mapping[str, Any]) -> str:
    canonical, _ = normalize_parameters(parameters)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_fingerprint(parameters: Mapping[str, Any]) -> str:
    """Fingerprint only the canonical semantic control document.

    This is useful for parameter comparison.  It is intentionally *not* enough
    to identify rendered audio, because two persistent speaker artifacts may use
    identical controls while representing different synthetic identities.
    """
    return hashlib.sha256(canonical_json(parameters).encode("utf-8")).hexdigest()


def artifact_fingerprint(
    parameters: Mapping[str, Any],
    *,
    provider: str,
    provider_voice_id: str,
    model_revision: str = "",
) -> str:
    """Fingerprint the full render identity: controls + model artifact mapping.

    Use this value for saved versions, preview provenance, production snapshots,
    and synthesis-cache discriminators.  It prevents two distinct model artifacts
    with the same parameter recipe from colliding.
    """
    payload = {
        "canonical_parameters": json.loads(canonical_json(parameters)),
        "provider": str(provider or ""),
        "provider_voice_id": str(provider_voice_id or ""),
        "model_revision": str(model_revision or ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def control_catalog(mode: str = "laboratory", search: str | None = None) -> list[dict[str, Any]]:
    normalized_mode = mode.lower()
    if normalized_mode == "automation":
        controls = [control for control in _CONTROLS if control.automatable]
    else:
        if normalized_mode not in MODE_RANK:
            raise ParameterValidationError("mode must be simple, studio, laboratory, or automation")
        requested_rank = MODE_RANK[normalized_mode]
        controls = [
            control for control in _CONTROLS
            if MODE_RANK[_effective_mode(control)] <= requested_rank
        ]
    if search:
        needle = search.strip().lower()
        controls = [
            control for control in controls
            if needle in control.path.lower()
            or needle in control.label.lower()
            or needle in control.description.lower()
            or needle in " ".join(control.tags).lower()
        ]
    group_order = {group["id"]: group["order"] for group in GROUPS}
    controls.sort(key=lambda item: (group_order[item.group], item.label.lower()))
    result: list[dict[str, Any]] = []
    for control in controls:
        item = control.as_dict()
        item["mode"] = _effective_mode(control)
        result.append(item)
    return result


def validate_parameter_paths(paths: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for path in paths:
        if not isinstance(path, str) or path not in CONTROL_BY_PATH:
            raise ParameterValidationError(f"Unknown lock/automation parameter path: {path!r}")
        if path not in normalized:
            normalized.append(path)
    return normalized


def parameter_value(parameters: Mapping[str, Any], path: str) -> Any:
    if path not in CONTROL_BY_PATH:
        raise ParameterValidationError(f"Unknown Voice City parameter path: {path}")
    return get_path(parameters, path)


def set_parameter_value(parameters: dict[str, Any], path: str, value: Any) -> None:
    if path not in CONTROL_BY_PATH:
        raise ParameterValidationError(f"Unknown Voice City parameter path: {path}")
    _set_path(parameters, path, value)


def schema_document(mode: str = "laboratory", search: str | None = None) -> dict[str, Any]:
    controls = control_catalog(mode=mode, search=search)
    counts = {
        name: len(control_catalog(name))
        for name in ("simple", "studio", "laboratory", "automation")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "architecture": "semantic-controls-over-validated-model-contract",
        "modes": [
            {"id": "simple", "label": "Simple", "control_count": counts["simple"]},
            {"id": "studio", "label": "Studio", "control_count": counts["studio"]},
            {"id": "laboratory", "label": "Laboratory", "control_count": counts["laboratory"]},
            {"id": "automation", "label": "Automation", "control_count": counts["automation"]},
        ],
        "groups": GROUPS,
        "controls": controls,
        "defaults": default_parameters(),
        "constraints": [
            "resonance weights are normalized",
            "extreme breathiness and pressed effort are mutually constrained",
            "combined texture is bounded for intelligibility",
            "accent transformations are bounded to avoid caricature",
            "spoken vibrato and room effects are narration-safe",
            "unknown future-version paths are rejected",
        ],
    }
