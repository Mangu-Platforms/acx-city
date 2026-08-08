"""Provider registry: single place the app asks for TTS engines."""
from typing import Dict, List, Optional

from .base import SpeechProvider
from .edge_provider import EdgeProvider
from .fake_provider import FakeSpeechProvider
from .polly_provider import PollyProvider
from .voice_city_provider import VoiceCityProvider


class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, SpeechProvider] = {}
        for provider in (EdgeProvider(), PollyProvider(), VoiceCityProvider(), FakeSpeechProvider()):
            self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[SpeechProvider]:
        return self._providers.get(name)

    def default(self) -> SpeechProvider:
        """Prefer the first available free provider, then anything available."""
        for p in self._providers.values():
            if getattr(p, "catalog_discoverable", True) and not p.paid and p.is_available():
                return p
        for p in self._providers.values():
            if getattr(p, "catalog_discoverable", True) and p.is_available():
                return p
        # Nothing configured: still return edge so errors are explicit at synth time
        return self._providers["edge"]

    def describe_all(self) -> List[Dict]:
        return [p.describe() for p in self._providers.values()]
