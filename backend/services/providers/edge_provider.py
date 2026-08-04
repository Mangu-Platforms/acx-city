"""Microsoft Edge neural voices via the free edge-tts service.

No API key or account required. Quality is comparable to paid neural TTS,
which makes it the default engine for personal use.
"""
import asyncio
import logging
from typing import Dict, List, Optional

from .base import SpeechProvider

log = logging.getLogger("audiobook.providers.edge")

# Curated fallback list used when the live voice listing is unreachable.
_CURATED_VOICES = [
    ("en-US-AvaNeural", "Ava", "en-US", "Female"),
    ("en-US-AndrewNeural", "Andrew", "en-US", "Male"),
    ("en-US-EmmaNeural", "Emma", "en-US", "Female"),
    ("en-US-BrianNeural", "Brian", "en-US", "Male"),
    ("en-US-AriaNeural", "Aria", "en-US", "Female"),
    ("en-US-JennyNeural", "Jenny", "en-US", "Female"),
    ("en-US-GuyNeural", "Guy", "en-US", "Male"),
    ("en-US-ChristopherNeural", "Christopher", "en-US", "Male"),
    ("en-US-MichelleNeural", "Michelle", "en-US", "Female"),
    ("en-GB-SoniaNeural", "Sonia", "en-GB", "Female"),
    ("en-GB-RyanNeural", "Ryan", "en-GB", "Male"),
    ("en-GB-LibbyNeural", "Libby", "en-GB", "Female"),
    ("en-AU-NatashaNeural", "Natasha", "en-AU", "Female"),
    ("en-AU-WilliamNeural", "William", "en-AU", "Male"),
    ("en-IN-NeerjaNeural", "Neerja", "en-IN", "Female"),
    ("en-IN-PrabhatNeural", "Prabhat", "en-IN", "Male"),
]


def _run(coro):
    """Run a coroutine from sync code, tolerating an already-running loop."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


class EdgeProvider(SpeechProvider):
    name = "edge"
    display_name = "Microsoft Edge (free)"
    max_chars = 5000
    paid = False

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False

    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        voices = None
        try:
            import edge_tts

            raw = _run(edge_tts.list_voices())
            voices = [
                {
                    "id": v["ShortName"],
                    "name": v["ShortName"].split("-")[-1].replace("Neural", ""),
                    "language": v["Locale"],
                    "gender": v["Gender"],
                    "neural": True,
                }
                for v in raw
            ]
        except Exception as e:  # noqa: BLE001
            log.warning("live voice listing failed, using curated list: %s", e)
        if not voices:
            voices = [
                {"id": vid, "name": name, "language": lang, "gender": gender, "neural": True}
                for vid, name, lang, gender in _CURATED_VOICES
            ]
        if language:
            voices = [v for v in voices if v["language"].lower().startswith(language.lower()[:2])]
        return voices

    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        return self.synthesize_with_options(text, voice_id, engine=engine)

    def synthesize_with_options(
        self, text: str, voice_id: str, engine: str = "neural", *,
        rate: Optional[str] = None, pitch: Optional[str] = None,
        volume: Optional[str] = None, style: Optional[str] = None,
    ) -> bytes:
        import edge_tts

        async def _synth() -> bytes:
            communicate = edge_tts.Communicate(
                text, voice_id, rate=rate or "+0%", pitch=pitch or "+0Hz", volume=volume or "+0%"
            )
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        audio = _run(_synth())
        if not audio:
            raise RuntimeError("edge-tts returned no audio")
        return audio
