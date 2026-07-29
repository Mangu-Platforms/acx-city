"""Audition-room preview renderer.

Turns one preview request into (a) a durable :class:`VoiceCityPreview` row,
(b) an MP3 object plus a provenance sidecar in object storage, and (c) a JSON
payload for the frontend audition room.

Contract with ``voice_city/api.py`` (the only consumer):

* ``PreviewRenderer.render`` adds and flushes the ORM row but never commits;
  the API layer owns the transaction and commits (or rolls back on error).
* Failures raise :class:`PreviewError` (mapped to HTTP 400).  Before raising,
  the row is marked ``failed`` with the error text so the state is coherent if
  the caller chooses to commit anyway.
* Storage layout is fixed; the API's delete endpoint hard-codes the
  provenance key::

      org/{organization_id}/voice-city/previews/{preview_id}/preview.mp3
      org/{organization_id}/voice-city/previews/{preview_id}/provenance.json

The provenance sidecar records hashes and counts, never manuscript text.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from db.voice_models import VoiceCityPreview
from services.providers import ProviderRegistry
from services.providers.base import SpeechProvider
from storage import get_storage

from .parameter_mapper import map_parameters
from .parameter_schema import artifact_fingerprint, get_path, merge_parameter_patch
from .pronunciation_engine import apply_pronunciation_rules

#: ACX-compatible loudness target; matches ``utils/audio_utils.py``.
LOUDNESS_TARGET_DBFS = -20.0
#: Number of buckets in the coarse waveform envelope returned to the client.
WAVEFORM_BUCKETS = 48
#: Fallback speaking rate used to estimate duration when MP3 decoding is
#: unavailable (typical neural-TTS narration pace).
_FALLBACK_WORDS_PER_MINUTE = 165.0

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DOWNLOAD_NAME = "voice-city-preview.mp3"


def _preview_max_chars() -> int:
    """Character cap for one preview render.

    Uses the same environment variable and default that
    ``VoiceCityService.capabilities()`` advertises to clients as
    ``preview_max_characters``, so the limit the UI displays is the limit the
    renderer enforces.
    """
    return int(os.getenv("VOICE_CITY_PREVIEW_MAX_CHARS", "1800"))


def _signed_url_ttl_s() -> int:
    return int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))


class PreviewError(Exception):
    """Raised when a preview cannot be rendered (bad input, provider or storage failure)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Deterministically split ``text`` into provider-sized chunks.

    Previews are capped well below provider limits, so the common case is a
    single chunk; sentence-boundary packing is a defensive fallback.
    """
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence:
            continue
        while len(sentence) > max_chars:  # pathological unbroken run
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def _bucket_peaks(values: Sequence[float], buckets: int) -> list[float]:
    """Reduce a sample sequence to per-bucket peak magnitudes."""
    total = len(values)
    if total == 0:
        return [0.0] * buckets
    peaks: list[float] = []
    for index in range(buckets):
        start = (index * total) // buckets
        end = max(((index + 1) * total) // buckets, start + 1)
        peaks.append(max(values[start:end], default=0.0))
    return peaks


def _normalize_waveform(peaks: Sequence[float], *, reference: float, loudness_match: bool) -> list[float]:
    """Scale bucket peaks into 0..1 floats.

    With ``loudness_match`` the envelope is peak-normalized so differently
    loud voices display comparably (the loudness-matched presentation); without
    it the envelope is scaled against the format's absolute full-scale
    ``reference`` so quieter renders visibly stay smaller.
    """
    observed = max(peaks, default=0.0)
    scale = observed if loudness_match else reference
    if scale <= 0.0:
        return [0.0] * len(peaks)
    return [round(min(value / scale, 1.0), 4) for value in peaks]


def _analyze_audio(
    audio: bytes, text: str, *, loudness_match: bool
) -> tuple[float, float | None, float | None, list[float]]:
    """Return ``(duration_s, loudness_dbfs, peak_dbfs, waveform)`` for MP3 bytes.

    ``pydub`` is imported at call time only: when it (and its ffmpeg backend)
    is present we measure the decoded PCM; otherwise we fall back to a
    words-per-minute duration estimate and a deterministic pseudo-envelope
    computed from the encoded bytes.  This module never hard-depends on pydub.
    """
    try:
        from pydub import AudioSegment  # deliberate call-time import

        segment = AudioSegment.from_file(io.BytesIO(audio), format="mp3")
        duration_s = round(len(segment) / 1000.0, 3)
        loudness = segment.dBFS
        peak = segment.max_dBFS
        loudness_dbfs = round(loudness, 1) if loudness != float("-inf") else None
        peak_dbfs = round(peak, 1) if peak != float("-inf") else None
        samples = [abs(int(sample)) for sample in segment.get_array_of_samples()]
        reference = float(segment.max_possible_amplitude)
        waveform = _normalize_waveform(
            _bucket_peaks([float(sample) for sample in samples], WAVEFORM_BUCKETS),
            reference=reference,
            loudness_match=loudness_match,
        )
        return duration_s, loudness_dbfs, peak_dbfs, waveform
    except Exception:
        words = max(len(text.split()), 1)
        duration_s = round(words * 60.0 / _FALLBACK_WORDS_PER_MINUTE, 3)
        # Coarse deterministic envelope straight from the encoded byte stream.
        # It tracks frame energy only loosely but is stable for a given render.
        magnitudes = [float(abs(byte - 128)) for byte in audio]
        waveform = _normalize_waveform(
            _bucket_peaks(magnitudes, WAVEFORM_BUCKETS),
            reference=128.0,
            loudness_match=loudness_match,
        )
        return duration_s, None, None, waveform


class PreviewRenderer:
    """Stateless renderer for audition previews.

    Safe to construct at import time: the provider registry instantiates
    provider adapters without touching the network.
    """

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self._registry = registry or ProviderRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def render(
        self,
        db: Session,
        *,
        organization_id: str,
        user_id: str | None,
        parameters: Mapping[str, Any],
        provider: str,
        provider_voice_id: str,
        text: str,
        voice_id: str | None,
        voice_version_id: str | None,
        candidate_id: str | None,
        script_id: str | None,
        overrides: Mapping[str, Any] | None,
        pronunciation_rules: Sequence[Mapping[str, Any]] | None,
        engine: str,
        model_revision: str,
        loudness_match: bool,
    ) -> tuple[VoiceCityPreview, dict[str, Any]]:
        """Render one preview and return ``(preview_row, result_dict)``.

        ``result_dict`` is spread directly into the API's JSON response, so its
        keys are part of the frontend contract (see module docstring); it never
        reuses the keys the API adds itself (``id``, ``status``, ``duration_s``,
        ``display_name``, ``preview_id``, ``segment_index``, ``text``).
        """
        # 1. Validate the text before spending anything on synthesis.
        requested_text = str(text or "").strip()
        if not requested_text:
            raise PreviewError("Preview text is required (provide text or a valid script_id)")
        max_chars = _preview_max_chars()
        if len(requested_text) > max_chars:
            raise PreviewError(
                f"Preview text is limited to {max_chars} characters; got {len(requested_text)}"
            )
        if not provider_voice_id:
            raise PreviewError("A provider voice id is required to render a preview")
        engine_name = str(engine or "neural")

        # 2. Merge ephemeral overrides into the canonical parameter document.
        #    merge_parameter_patch re-normalizes, so constraint warnings surface
        #    here; ParameterValidationError propagates (the API maps it to 400).
        merged, parameter_warnings = merge_parameter_patch(dict(parameters or {}), dict(overrides or {}))

        # 3. Apply the pronunciation dictionary to the spoken text.
        raw_strength = get_path(merged, "interpretation.pronunciation_rule_strength", 1.0)
        try:
            strength = float(raw_strength) if raw_strength is not None else 1.0
        except (TypeError, ValueError):
            strength = 1.0
        rules = list(pronunciation_rules or [])
        try:
            processed_text, applied_rules = apply_pronunciation_rules(requested_text, rules, strength=strength)
        except Exception as exc:
            raise PreviewError(f"Pronunciation rules could not be applied: {exc}") from exc
        processed_text = str(processed_text or "").strip() or requested_text
        applied_count = len(applied_rules) if hasattr(applied_rules, "__len__") else int(applied_rules or 0)

        # 4. Translate semantic controls into the provider render plan.
        try:
            plan = map_parameters(merged, provider=provider, provider_voice_id=provider_voice_id, engine=engine_name)
            plan_summary = {
                "rate": plan.rate,
                "pitch": plan.pitch,
                "volume": plan.volume,
                "style": plan.style,
                "cache_discriminator": str(plan.cache_discriminator()),
            }
        except PreviewError:
            raise
        except Exception as exc:
            raise PreviewError(f"Could not build a provider render plan: {exc}") from exc

        # 5. Resolve the provider before creating any durable state.
        speech = self._registry.get(str(provider or ""))
        if speech is None:
            raise PreviewError(f"Unknown synthesis provider '{provider}'")
        if not speech.is_available():
            raise PreviewError(
                f"Provider '{speech.name}' is not available right now; "
                "check its configuration (e.g. credentials) and retry"
            )

        voice_fingerprint = artifact_fingerprint(
            merged,
            provider=str(provider or ""),
            provider_voice_id=str(provider_voice_id or ""),
            model_revision=str(model_revision or ""),
        )
        content_hash = _sha256(
            json.dumps(
                {
                    "engine": engine_name,
                    "provider": str(provider or ""),
                    "provider_voice_id": str(provider_voice_id or ""),
                    "render_plan_discriminator": plan_summary["cache_discriminator"],
                    "text": processed_text,
                    "voice_fingerprint": voice_fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

        # Flush (not commit) so preview.id exists for the storage key layout;
        # the API layer owns commit/rollback.
        preview = VoiceCityPreview(
            organization_id=organization_id,
            created_by=user_id,
            voice_version_id=voice_version_id,
            candidate_id=candidate_id,
            script_id=script_id,
            text=requested_text,
            parameter_overrides=dict(overrides or {}),
            provider=str(provider or ""),
            provider_voice_id=str(provider_voice_id or ""),
            content_hash=content_hash,
            voice_fingerprint=voice_fingerprint,
            status="rendering",
        )
        db.add(preview)
        db.flush()

        audio_key = f"org/{organization_id}/voice-city/previews/{preview.id}/preview.mp3"
        provenance_key = f"org/{organization_id}/voice-city/previews/{preview.id}/provenance.json"

        try:
            # 6. Synthesize, analyze, and persist audio plus provenance.
            audio = self._synthesize(speech, processed_text, str(provider_voice_id), plan, engine=engine_name)
            duration_s, loudness_dbfs, peak_dbfs, waveform = _analyze_audio(
                audio, processed_text, loudness_match=bool(loudness_match)
            )
            # Honest limitation: without a guaranteed encoder (ffmpeg) we do not
            # re-encode the MP3 to the loudness target.  loudness_match is
            # honored by peak-normalizing the waveform envelope and reporting
            # the measured level and the gain a player would apply; the stored
            # audio bytes are the provider's untouched output.
            loudness = {
                "target_dbfs": LOUDNESS_TARGET_DBFS,
                "measured_dbfs": loudness_dbfs,
                "peak_dbfs": peak_dbfs,
                "gain_db": (
                    round(LOUDNESS_TARGET_DBFS - loudness_dbfs, 1)
                    if (loudness_match and loudness_dbfs is not None)
                    else 0.0
                ),
                "matched": bool(loudness_match) and loudness_dbfs is not None,
            }
            provenance = {
                "schema": "voice-city-preview-provenance-v1",
                "preview_id": preview.id,
                "organization_id": organization_id,
                "created_by": user_id,
                "created_at": preview.created_at.isoformat() if preview.created_at else None,
                "voice_id": voice_id,
                "voice_version_id": voice_version_id,
                "candidate_id": candidate_id,
                "script_id": script_id,
                "provider": str(provider or ""),
                "provider_voice_id": str(provider_voice_id or ""),
                "engine": engine_name,
                "model_revision": str(model_revision or ""),
                "parameter_fingerprint": voice_fingerprint,
                "content_hash": content_hash,
                "audio_sha256": _sha256(audio),
                "audio_bytes": len(audio),
                "duration_s": duration_s,
                # Hashes only: the sidecar must never contain manuscript text.
                "text_sha256": _sha256(requested_text.encode("utf-8")),
                "processed_text_sha256": _sha256(processed_text.encode("utf-8")),
                "text_characters": len(processed_text),
                "pronunciation_rules": {"provided": len(rules), "applied": applied_count},
                "parameter_warnings": list(parameter_warnings),
                "render_plan": plan_summary,
                "loudness": loudness,
                "loudness_match": bool(loudness_match),
                "synthetic_only": True,
                "reference_audio": False,
            }
            storage = get_storage()
            storage.put_bytes(audio_key, audio, content_type="audio/mpeg")
            storage.put_bytes(
                provenance_key,
                json.dumps(provenance, sort_keys=True, indent=2).encode("utf-8"),
                content_type="application/json",
            )
            signed = storage.signed_url(audio_key, expires_in=_signed_url_ttl_s(), download_name=_DOWNLOAD_NAME)
        except PreviewError as exc:
            preview.status = "failed"
            preview.error = str(exc)
            raise
        except Exception as exc:
            preview.status = "failed"
            preview.error = str(exc)
            raise PreviewError(f"Preview could not be rendered: {exc}") from exc

        # 7. Mark the row ready.  The API commits.
        preview.audio_key = audio_key
        preview.duration_s = duration_s
        preview.status = "ready"
        preview.error = None

        result: dict[str, Any] = {
            "url": signed.url,
            "expires_in": signed.expires_in,
            "waveform": waveform,
            "loudness": loudness,
            "loudness_match": bool(loudness_match),
            "engine": engine_name,
            "provider": preview.provider,
            "provider_voice_id": preview.provider_voice_id,
            "script_id": script_id,
            "content_hash": content_hash,
            "voice_fingerprint": voice_fingerprint,
            "provenance_key": provenance_key,
            "applied_pronunciation_rules": applied_count,
            "parameter_warnings": list(parameter_warnings),
        }
        return preview, result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _synthesize(
        self,
        speech: SpeechProvider,
        text: str,
        provider_voice_id: str,
        plan: Any,
        *,
        engine: str,
    ) -> bytes:
        """Render ``text`` through ``speech`` and return MP3 bytes.

        Prefers the prosody-aware ``synthesize_with_options`` entry point and
        falls back to plain ``synthesize``.  Preview text is capped well below
        provider limits, so chunking is only a defensive path; back-to-back
        MPEG frame sequences concatenate into a playable stream.
        """
        max_chars = max(int(getattr(speech, "max_chars", 3000) or 3000), 200)
        rendered: list[bytes] = []
        for chunk in _chunk_text(text, max_chars):
            try:
                if hasattr(speech, "synthesize_with_options"):
                    audio = speech.synthesize_with_options(
                        chunk,
                        provider_voice_id,
                        engine=engine,
                        rate=plan.rate,
                        pitch=plan.pitch,
                        volume=plan.volume,
                        style=plan.style,
                    )
                else:
                    audio = speech.synthesize(chunk, provider_voice_id, engine)
            except Exception as exc:
                raise PreviewError(
                    f"Provider '{speech.name}' failed to synthesize the preview: {exc}"
                ) from exc
            if not audio:
                raise PreviewError(f"Provider '{speech.name}' returned no audio for the preview")
            rendered.append(bytes(audio))
        return b"".join(rendered)
