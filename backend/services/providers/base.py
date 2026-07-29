"""Speech provider contract.

Every TTS engine (AWS Polly, Microsoft Edge, future ones) implements this
interface. The rest of the app never talks to a vendor SDK directly, so new
engines can be added without touching the pipeline.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class SpeechProvider(ABC):
    #: machine name used in API requests, e.g. "polly", "edge"
    name: str = "base"
    #: human-friendly label
    display_name: str = "Base provider"
    #: max characters this provider accepts per synthesis call
    max_chars: int = 3000
    #: True if using this provider costs money
    paid: bool = True
    #: approximate USD cost per 1,000,000 characters synthesized (for the cost
    #: ledger / quota estimates). 0 for free providers. Override per provider.
    cost_per_million_chars: float = 0.0
    #: False for organization-owned artifacts that must not appear in the global catalog.
    catalog_discoverable: bool = True

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the provider is configured and usable right now."""

    @abstractmethod
    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        """Return voices as dicts: {id, name, language, gender, neural}."""

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        """Synthesize one chunk of text (<= max_chars) and return MP3 bytes.

        Raises on failure; the pipeline handles retries.
        """

    def synthesize_with_options(
        self, text: str, voice_id: str, engine: str = "neural", *,
        rate: Optional[str] = None, pitch: Optional[str] = None,
        volume: Optional[str] = None, style: Optional[str] = None,
    ) -> bytes:
        """Render semantic prosody options when supported.

        Catalog providers remain compatible by falling back to ``synthesize``.
        """
        return self.synthesize(text, voice_id, engine)

    def describe(self) -> Dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "available": self.is_available(),
            "paid": self.paid,
            "max_chars": self.max_chars,
            "cost_per_million_chars": self.cost_per_million_chars,
            "catalog_discoverable": self.catalog_discoverable,
        }
