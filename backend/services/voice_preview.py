"""
Voice Preview Service — instant 5-second voice samples for ACX City.

Provides quick audition capabilities: single-voice preview, character-based
preview, side-by-side comparison, and batch previews for faster casting.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Predefined audition scripts by genre / mood
# ---------------------------------------------------------------------------

PREVIEW_SCRIPTS: dict[str, dict[str, str]] = {
    "narrative": {
        "label": "Narrative",
        "text": (
            "The city stretched below like a circuit board, each light a story "
            "waiting to be told. She pressed her palm against the cold glass of "
            "the observation deck and whispered, 'This is where it all begins.'"
        ),
    },
    "dialogue": {
        "label": "Dialogue",
        "text": (
            "\"You can't be serious,\" Marcus said, folding his arms. "
            "\"I've never been more serious in my life,\" she replied, "
            "tossing the keys onto the table. \"We leave at dawn.\""
        ),
    },
    "action": {
        "label": "Action",
        "text": (
            "The explosion ripped through the corridor. Debris rained down as "
            "Jax sprinted forward, vaulting over a collapsed beam. \"Move! Move! "
            "Move!\" he shouted, pulling the injured soldier behind cover."
        ),
    },
    "romance": {
        "label": "Romance",
        "text": (
            "His fingertips traced the curve of her jaw, feather-light. The "
            "world outside the rain-streaked window had ceased to exist. "
            "\"I waited years to hear you say that,\" he murmured."
        ),
    },
    "thriller": {
        "label": "Thriller",
        "text": (
            "The phone rang at exactly 3:17 AM — the third night in a row. "
            "She lifted the receiver with a trembling hand. Silence. Then, a "
            "whisper: \"Check the closet.\" The line went dead."
        ),
    },
}


# ---------------------------------------------------------------------------
# Protocol / interface for providers (edge-tts, polly, etc.)
# ---------------------------------------------------------------------------

class TTSProvider(Protocol):
    """Minimal interface a TTS provider must satisfy."""

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        *,
        emotion: Optional[str] = None,
        output_format: str = "mp3",
        sample_rate: int = 24000,
        **kwargs: Any,
    ) -> bytes:
        """Return raw audio bytes."""
        ...


class StorageBackend(Protocol):
    """Stores audio and returns a retrievable key / URL."""

    async def upload(self, data: bytes, key: str, content_type: str = "audio/mpeg") -> str:
        """Upload bytes, return the storage key."""
        ...

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a (possibly signed) URL for the stored object."""
        ...


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PreviewResult:
    audio_key: str
    duration_s: float
    url: str
    voice_id: str
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_key": self.audio_key,
            "duration_s": self.duration_s,
            "url": self.url,
            "voice_id": self.voice_id,
            "provider": self.provider,
            **self.metadata,
        }


# ---------------------------------------------------------------------------
# Voice Preview Service
# ---------------------------------------------------------------------------

class VoicePreviewService:
    """
    Instant voice-preview generation for ACX City.

    Synthesises short (default 5 s) audio clips so narrators and publishers
    can audition voices before committing to a full chapter.
    """

    def __init__(
        self,
        storage_backend: StorageBackend,
        provider_registry: dict[str, TTSProvider],
    ) -> None:
        self._storage = storage_backend
        self._providers = provider_registry

    # -- internal helpers --------------------------------------------------

    def _get_provider(self, name: str) -> TTSProvider:
        try:
            return self._providers[name]
        except KeyError:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise ValueError(
                f"Unknown TTS provider '{name}'. Available: {available}"
            ) from None

    @staticmethod
    def _build_key(voice_id: str, provider: str, suffix: str = "mp3") -> str:
        ts = int(time.time())
        short_uuid = uuid.uuid4().hex[:8]
        return f"previews/{provider}/{voice_id}/{ts}_{short_uuid}.{suffix}"

    # -- public API --------------------------------------------------------

    async def preview_voice(
        self,
        text: str,
        voice_id: str,
        provider: str = "edge",
        emotion: Optional[str] = None,
        duration_s: float = 5.0,
    ) -> dict[str, Any]:
        """
        Synthesise a short preview clip for a single voice.

        Args:
            text: Script text to speak.
            voice_id: Provider-specific voice identifier.
            provider: TTS provider name (default ``"edge"``).
            emotion: Optional emotion / style hint.
            duration_s: Target duration in seconds (advisory).

        Returns:
            Dict with ``audio_key``, ``duration_s``, ``url``.
        """
        tts = self._get_provider(provider)
        audio_bytes = await tts.synthesize(text, voice_id, emotion=emotion)
        key = self._build_key(voice_id, provider)
        await self._storage.upload(audio_bytes, key)
        url = self._storage.get_url(key)

        # Estimate duration from byte length (rough: 16 kB/s for 128 kbps mp3)
        est_duration = round(len(audio_bytes) / 16_000, 2) if audio_bytes else duration_s

        result = PreviewResult(
            audio_key=key,
            duration_s=est_duration,
            url=url,
            voice_id=voice_id,
            provider=provider,
        )
        logger.info("Preview generated: voice=%s provider=%s key=%s", voice_id, provider, key)
        return result.to_dict()

    async def preview_character(
        self,
        character_voice_map_id: str,
        text: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Preview the voice assigned to a character via a voice-map entry.

        Args:
            character_voice_map_id: ID referencing a row in the
                ``character_voice_map`` table.
            text: Custom script. Falls back to the *dialogue* preset.

        Returns:
            Preview result dict.
        """
        # Lazy import to avoid circular deps at module level
        from backend.repositories import character_voice_map_repo  # type: ignore[import-untyped]

        mapping = await character_voice_map_repo.get(character_voice_map_id)
        if mapping is None:
            raise KeyError(f"Character voice map '{character_voice_map_id}' not found.")

        script = text or PREVIEW_SCRIPTS["dialogue"]["text"]
        return await self.preview_voice(
            text=script,
            voice_id=mapping["voice_id"],
            provider=mapping.get("provider", "edge"),
            emotion=mapping.get("emotion"),
        )

    async def compare_voices(
        self,
        voice_ids: list[str],
        text: str,
        blind: bool = False,
    ) -> dict[str, Any]:
        """
        Generate side-by-side previews for multiple voices.

        Args:
            voice_ids: List of voice IDs to compare.
            text: Script text shared across all clips.
            blind: If ``True``, anonymise voice IDs (``A``, ``B``, …)
                so the listener isn't biased.

        Returns:
            ``{"comparison_id": …, "clips": [...]}``
        """
        if len(voice_ids) < 2:
            raise ValueError("Need at least two voice IDs to compare.")
        if len(voice_ids) > 10:
            raise ValueError("Comparison is limited to 10 voices at a time.")

        comparison_id = uuid.uuid4().hex[:12]
        clips: list[dict[str, Any]] = []

        labels = [chr(ord("A") + i) for i in range(len(voice_ids))]

        for idx, vid in enumerate(voice_ids):
            result = await self.preview_voice(text=text, voice_id=vid)
            clip: dict[str, Any] = {
                "index": idx,
                "audio_key": result["audio_key"],
                "url": result["url"],
                "duration_s": result["duration_s"],
            }
            if blind:
                clip["label"] = labels[idx]
                clip["voice_id"] = f"blind_{labels[idx]}"
            else:
                clip["voice_id"] = vid
            clips.append(clip)

        return {"comparison_id": comparison_id, "clips": clips}

    async def batch_preview(
        self,
        voice_ids: list[str],
        script_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Generate previews for many voices using a shared script.

        Args:
            voice_ids: Voices to preview.
            script_id: Key from :data:`PREVIEW_SCRIPTS`. Defaults to
                ``"narrative"``.

        Returns:
            List of preview result dicts.
        """
        script_entry = PREVIEW_SCRIPTS.get(script_id or "narrative", PREVIEW_SCRIPTS["narrative"])
        text = script_entry["text"]

        results: list[dict[str, Any]] = []
        for vid in voice_ids:
            res = await self.preview_voice(text=text, voice_id=vid)
            res["script_id"] = script_id or "narrative"
            results.append(res)

        logger.info(
            "Batch preview: %d voices, script=%s", len(voice_ids), script_id or "narrative"
        )
        return results
