"""SpeechProvider adapter for persistent Voice City model artifacts."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from .base import SpeechProvider
from services.voice_city.generative_provider import RemoteGenerativeVoiceProvider


class VoiceCityProvider(SpeechProvider):
    name = "voice-city"
    display_name = "Voice City Model Server"
    max_chars = int(os.getenv("VOICE_CITY_MODEL_MAX_CHARS", "5000"))
    paid = os.getenv("VOICE_CITY_MODEL_PROVIDER_PAID", "false").lower() == "true"
    catalog_discoverable = False
    cost_per_million_chars = float(os.getenv("VOICE_CITY_MODEL_COST_PER_MILLION_CHARS", "0"))

    def __init__(self):
        self.client = RemoteGenerativeVoiceProvider()

    def is_available(self) -> bool:
        return self.client.is_available()

    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        # Persistent artifacts are organization-owned and therefore listed through
        # the authenticated Voice City API, never the global catalog endpoint.
        return []

    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        return self.client.synthesize(
            text=text,
            voice_artifact_id=voice_id,
            performance_parameters={"engine": engine},
        )

    def synthesize_with_options(
        self, text: str, voice_id: str, engine: str = "neural", *,
        rate: Optional[str] = None, pitch: Optional[str] = None,
        volume: Optional[str] = None, style: Optional[str] = None,
    ) -> bytes:
        return self.client.synthesize(
            text=text,
            voice_artifact_id=voice_id,
            performance_parameters={
                "engine": engine,
                "rate": rate,
                "pitch": pitch,
                "volume": volume,
                "style": style,
            },
        )
