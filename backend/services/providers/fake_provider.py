"""Deterministic offline TTS provider for testing.

Registered as provider name "fake". Never appears in the public catalog
(catalog_discoverable=False). Returns reproducible MP3-shaped bytes so the
pipeline's file-writing and QC paths complete without ffmpeg or network.

Enable via SPEECH_FAKE_PROVIDER=true or by directly naming provider="fake"
in a job. The pipeline will find it in the registry regardless.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from .base import SpeechProvider

_VOICES = [
    {"id": "fake-a", "name": "Fake Voice A", "language": "en-US", "gender": "female", "neural": True},
    {"id": "fake-b", "name": "Fake Voice B", "language": "en-US", "gender": "male", "neural": True},
]


class FakeSpeechProvider(SpeechProvider):
    """Deterministic offline TTS provider.

    synthesize(text, voice_id) → b"ID3fake" + sha256(voice_id:text)[:16]

    The output is deterministic across retries and identical regardless of
    runtime environment, so tests never need network access or credentials.
    """

    name = "fake"
    display_name = "Fake (test)"
    max_chars = 100_000
    paid = False
    cost_per_million_chars = 0.0
    catalog_discoverable = False  # never appears in /api/providers or /api/voices

    def is_available(self) -> bool:
        return True

    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        return _VOICES

    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        digest = hashlib.sha256(f"{voice_id}:{text}".encode()).digest()
        return b"ID3fake" + digest[:16]

    def synthesize_with_options(
        self, text: str, voice_id: str, engine: str = "neural", *,
        rate: Optional[str] = None, pitch: Optional[str] = None,
        volume: Optional[str] = None, style: Optional[str] = None,
    ) -> bytes:
        return self.synthesize(text, voice_id, engine)
