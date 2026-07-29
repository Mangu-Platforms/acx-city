"""Map canonical semantic controls onto provider prosody plans and automation.

Why this module exists: Voice City's canonical parameter document is
provider-agnostic sound design, while the speech providers accept only the
tiny prosody contract of ``synthesize_with_options`` (``rate``/``pitch``/
``volume``/``style`` strings -- see ``services/providers/base.py``).  This
module is the single deterministic translation between the two, plus the
evaluator that applies snapshot automation tracks to a parameter document.

The mapping is deliberately *relative*: a control contributes a prosody
directive only when it differs from its schema default, so an undirected
render always produces an all-``None`` plan.  That keeps the plan's
``cache_discriminator`` stable across voices, providers, and releases, which
in turn keeps the synthesis cache warm for the common case
(``backend/jobs/pipeline.py`` folds the discriminator into its cache key).

Only the standard library and the sibling ``parameter_schema`` are imported;
automation tracks arrive as serialized snapshot dicts, never ORM rows.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .parameter_schema import CONTROL_BY_PATH, get_path, set_parameter_value

__all__ = ["ProviderRenderPlan", "map_parameters", "apply_automation"]

# Semantic source controls for the provider prosody contract.
_RATE_PATH = "performance.speaking_rate"
_PITCH_PATH = "identity.pitch_center"
_ENERGY_PATH = "performance.energy"
_LOUDNESS_PATH = "post.target_loudness"

# Bounded prosody excursions.  Edge (edge-tts) expects rate/volume as signed
# percentages ("+12%") and pitch in signed hertz ("+15Hz"); Polly SSML
# ``<prosody>`` accepts signed percentages for rate/volume and signed
# percentage pitch ("+10%"), which stays inside Polly's documented -33%..+50%
# pitch window at full deflection.
_PITCH_HZ_SPAN = 40.0
_PITCH_PERCENT_SPAN = 25.0
_ENERGY_VOLUME_SPAN = 30.0
_LOUDNESS_VOLUME_PER_DB = 4.0
_VOLUME_LIMIT = 50
# A named speaking style is only requested once an emotion clearly dominates.
_STYLE_THRESHOLD = 0.25
_STYLE_BY_PATH = {
    "emotion.anger": "angry",
    "emotion.calm": "calm",
    "emotion.fear": "fearful",
    "emotion.joy": "cheerful",
    "emotion.tenderness": "gentle",
    "performance.excitement": "excited",
    "performance.sadness": "sad",
}


@dataclass(frozen=True)
class ProviderRenderPlan:
    """Immutable provider prosody directives for one render segment.

    ``None`` means "no directive": providers fall back to their own neutral
    values (``+0%``/``+0Hz``).  The plan intentionally excludes provider and
    voice identity -- the pipeline cache key already contains those, and an
    all-``None`` plan must hash identically for every undirected render.
    """

    rate: str | None = None
    pitch: str | None = None
    volume: str | None = None
    style: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "rate": self.rate,
            "pitch": self.pitch,
            "volume": self.volume,
            "style": self.style,
        }

    def is_neutral(self) -> bool:
        return self.rate is None and self.pitch is None and self.volume is None and self.style is None

    def cache_discriminator(self) -> str:
        """Deterministic short hash of the full plan for synthesis-cache keys."""
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Canonical controls -> provider prosody
# ---------------------------------------------------------------------------

def _control_value(parameters: Any, path: str) -> tuple[float, float]:
    """Return ``(clamped_value, schema_default)`` for a slider control."""
    control = CONTROL_BY_PATH[path]
    default = float(control.default)
    raw = get_path(parameters, path, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default, default
    numeric = float(raw)
    if not math.isfinite(numeric):
        return default, default
    minimum = default if control.minimum is None else float(control.minimum)
    maximum = default if control.maximum is None else float(control.maximum)
    return min(maximum, max(minimum, numeric)), default


def _signed_percent(value: float) -> str | None:
    rounded = int(round(value))
    if rounded == 0:
        return None
    return f"{rounded:+d}%"


def _signed_hertz(value: float) -> str | None:
    rounded = int(round(value))
    if rounded == 0:
        return None
    return f"{rounded:+d}Hz"


def _dominant_style(parameters: Any) -> str | None:
    """Pick the single most-raised emotion control, if it clears the threshold.

    Iteration is over the sorted style table and ties resolve to the
    alphabetically first path, so the choice is deterministic.
    """
    best_path: str | None = None
    best_delta = _STYLE_THRESHOLD
    for path, style in sorted(_STYLE_BY_PATH.items()):
        value, default = _control_value(parameters, path)
        delta = value - default
        if delta > best_delta:
            best_delta = delta
            best_path = path
    return _STYLE_BY_PATH[best_path] if best_path else None


def map_parameters(
    parameters: Any, *, provider: str, provider_voice_id: str, engine: str
) -> ProviderRenderPlan:
    """Translate canonical semantic controls into one provider render plan.

    Mapping rules (all relative to schema defaults, so a neutral document
    yields an all-``None`` plan):

    - pace: ``performance.speaking_rate`` (a multiplier, default 1.0) becomes
      a signed rate percentage -- 1.12 -> "+12%", 0.92 -> "-8%".
    - pitch: ``identity.pitch_center`` (-1..1) spans +/-40Hz for Edge-style
      providers and +/-25% for Polly SSML prosody.
    - volume: ``performance.energy`` (span +/-30%) plus ``post.target_loudness``
      (4% per dB from the -20 dBFS default), bounded to +/-50%.
    - style: the dominant clearly-raised emotion control, when any
      (:data:`_STYLE_BY_PATH`); providers that cannot express a style simply
      ignore it.

    ``provider_voice_id`` and ``engine`` are part of the render identity that
    the pipeline hashes separately; they are accepted for signature parity and
    future provider-specific mappings but never folded into the plan, keeping
    neutral cache keys stable.
    """
    del provider_voice_id, engine  # identity is fingerprinted by the caller

    provider_key = str(provider or "").strip().lower()

    rate_value, rate_default = _control_value(parameters, _RATE_PATH)
    rate = _signed_percent((rate_value - rate_default) * 100.0)

    pitch_value, pitch_default = _control_value(parameters, _PITCH_PATH)
    pitch_delta = pitch_value - pitch_default
    if provider_key == "polly":
        pitch = _signed_percent(pitch_delta * _PITCH_PERCENT_SPAN)
    else:
        # Edge, the Voice City model server, and unknown providers all follow
        # the edge-tts convention of signed hertz.
        pitch = _signed_hertz(pitch_delta * _PITCH_HZ_SPAN)

    energy_value, energy_default = _control_value(parameters, _ENERGY_PATH)
    loudness_value, loudness_default = _control_value(parameters, _LOUDNESS_PATH)
    volume_span = (
        (energy_value - energy_default) * _ENERGY_VOLUME_SPAN
        + (loudness_value - loudness_default) * _LOUDNESS_VOLUME_PER_DB
    )
    volume = _signed_percent(min(float(_VOLUME_LIMIT), max(-float(_VOLUME_LIMIT), volume_span)))

    return ProviderRenderPlan(
        rate=rate,
        pitch=pitch,
        volume=volume,
        style=_dominant_style(parameters),
    )


# ---------------------------------------------------------------------------
# Automation tracks
# ---------------------------------------------------------------------------

def _clamp_position(position: Any, warnings: list[str]) -> float:
    try:
        numeric = float(position)
    except (TypeError, ValueError):
        warnings.append("Automation position was not numeric; using 0")
        return 0.0
    if not math.isfinite(numeric):
        warnings.append("Automation position was not finite; using 0")
        return 0.0
    return min(1.0, max(0.0, numeric))


def _keyframe_points(
    keyframes: Any, track_id: str, warnings: list[str]
) -> list[tuple[float, float]]:
    if not isinstance(keyframes, Sequence) or isinstance(keyframes, (str, bytes)):
        warnings.append(f"Automation track {track_id} has no keyframes; skipped")
        return []
    points: list[tuple[float, float]] = []
    for frame in keyframes:
        if not isinstance(frame, Mapping):
            warnings.append(f"Automation track {track_id} contains a malformed keyframe; ignored")
            continue
        try:
            at = float(frame["at"])
            value = float(frame["value"])
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Automation track {track_id} contains a malformed keyframe; ignored")
            continue
        if not (math.isfinite(at) and math.isfinite(value)):
            warnings.append(f"Automation track {track_id} contains a non-finite keyframe; ignored")
            continue
        points.append((min(1.0, max(0.0, at)), value))
    if not points:
        warnings.append(f"Automation track {track_id} has no usable keyframes; skipped")
        return []
    # Stable sort: keyframes sharing the same position keep their input order.
    points.sort(key=lambda item: item[0])
    return points


def _evaluate_track(
    points: list[tuple[float, float]],
    interpolation: str,
    position: float,
    track_id: str,
    warnings: list[str],
) -> float:
    """Evaluate keyframes at ``position`` using the track's interpolation.

    ``step`` holds each keyframe's value until the next keyframe begins;
    ``smooth`` (also accepted as ``smoothed``) applies the smoothstep easing
    ``t * t * (3 - 2t)`` between neighbors; ``linear`` interpolates directly.
    Positions outside the keyframe range clamp to the nearest endpoint.
    """
    if position <= points[0][0]:
        return points[0][1]
    if position >= points[-1][0]:
        return points[-1][1]

    if interpolation == "step":
        current = points[0][1]
        for at, value in points:
            if position >= at:
                current = value
            else:
                break
        return current

    if interpolation not in ("linear", "smooth", "smoothed"):
        warnings.append(
            f"Automation track {track_id} uses unknown interpolation "
            f"{interpolation!r}; treated as linear"
        )
        interpolation = "linear"

    for (start_at, start_value), (end_at, end_value) in zip(points, points[1:]):
        if start_at <= position <= end_at:
            span = end_at - start_at
            if span <= 1e-12:
                return end_value
            t = (position - start_at) / span
            if interpolation in ("smooth", "smoothed"):
                t = t * t * (3.0 - 2.0 * t)
            return start_value + (end_value - start_value) * t
    return points[-1][1]


def apply_automation(
    parameters: Any,
    tracks: Any,
    *,
    scope_type: str,
    scope_key: str,
    position: float,
    include_global: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Apply matching automation tracks to a deep copy of ``parameters``.

    ``tracks`` are serialized ``VoiceCityAutomationTrack`` snapshot dicts
    (``id``, ``scope_type``, ``scope_key``, ``parameter_path``, ``keyframes``,
    ``interpolation``, ``enabled``; extra keys are tolerated).  A track
    applies when it is enabled and either its ``scope_type``/``scope_key``
    equal the requested scope, or its ``scope_type`` is ``"global"`` and
    ``include_global`` is true -- production passes ``include_global`` for
    exactly one scope per segment so global tracks are applied once.

    Keyframes are evaluated at ``position`` (clamped to [0, 1]); resulting
    values are clamped to the control's schema range and written to a deep
    copy -- the input document is never mutated.  Tracks apply in input order,
    so when two tracks target the same path the later one wins (snapshots list
    narrator tracks before cast tracks deliberately).  Unknown parameter
    paths, non-slider controls, and malformed keyframes are skipped with a
    warning instead of failing a render.

    Returns ``(new_parameters, warnings)``.
    """
    result = copy.deepcopy(dict(parameters or {}))
    warnings: list[str] = []
    if not tracks:
        return result, warnings

    requested_type = str(scope_type or "").strip()
    requested_key = str(scope_key or "").strip()
    clamped_position = _clamp_position(position, warnings)

    for track in tracks:
        if not isinstance(track, Mapping):
            warnings.append("A malformed automation track was ignored")
            continue
        if not bool(track.get("enabled", True)):
            continue
        track_id = str(track.get("id") or "unknown")
        track_scope = str(track.get("scope_type") or "").strip()
        if track_scope == "global":
            if not include_global:
                continue
        elif not (
            track_scope == requested_type
            and str(track.get("scope_key") or "").strip() == requested_key
        ):
            continue

        path = str(track.get("parameter_path") or "")
        control = CONTROL_BY_PATH.get(path)
        if control is None:
            warnings.append(
                f"Automation track {track_id} targets unknown parameter {path!r}; skipped"
            )
            continue
        if control.control_type != "slider":
            warnings.append(
                f"Automation track {track_id} targets non-numeric parameter {path!r}; skipped"
            )
            continue

        points = _keyframe_points(track.get("keyframes"), track_id, warnings)
        if not points:
            continue
        value = _evaluate_track(
            points,
            str(track.get("interpolation") or "linear").strip().lower(),
            clamped_position,
            track_id,
            warnings,
        )
        minimum = float(control.minimum) if control.minimum is not None else value
        maximum = float(control.maximum) if control.maximum is not None else value
        clamped = min(maximum, max(minimum, value))
        if clamped != value:
            warnings.append(
                f"Automation track {track_id} value {value:g} was constrained "
                f"to {clamped:g} for {path}"
            )
        set_parameter_value(result, path, round(clamped, 6))
    return result, warnings
