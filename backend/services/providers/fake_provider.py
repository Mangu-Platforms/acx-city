"""Deterministic offline TTS provider that emits real, decodable audio.

Registered as provider name "fake". Never appears in the public catalog
(catalog_discoverable=False); it is only used when a job or directed segment
explicitly names provider="fake".

Success output is a genuine mono 24 kHz MP3 sine tone generated with ffmpeg's
lavfi source: the frequency derives from sha256(voice_id:text), and the
duration follows the same ~12.5 chars/sec spoken-English law the streaming
service uses (utils.audio_utils.CHARS_PER_SECOND), so identical input yields
byte-identical output and duration-plausibility checks are meaningful.

Failure modes emit specifically-shaped bad artifacts, each of which a distinct
media-validation rule must catch:

    invalid_audio    plausible byte length, garbage content, no valid header
    truncated_audio  valid MP3 header (claims full duration), cut mid-frame
    silent_audio     valid, decodable MP3 of pure digital silence
    wrong_duration   valid MP3, duration wildly off vs. character count
    wrong_format     valid audio, wrong codec/container (WAV)

plus exception modes: temporary_failure (raises once per unique input, then
succeeds — exercises retry), permanent_failure, rate_limited, and
fail_after_n_calls (set the attribute on the instance).

Select a mode per-call by embedding a marker in the text — "[fake:silent_audio]"
— (the marker is stripped before duration/frequency derivation) or per-instance
by setting `provider.mode`. The marker wins.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from .base import SpeechProvider
from utils.audio_utils import CHARS_PER_SECOND

_VOICES = [
    {"id": "fake-a", "name": "Fake Voice A", "language": "en-US", "gender": "female", "neural": True},
    {"id": "fake-b", "name": "Fake Voice B", "language": "en-US", "gender": "male", "neural": True},
]

_MARKER_RE = re.compile(r"\[fake:([a-z_]+)\]")

ARTIFACT_MODES = frozenset({
    "success", "invalid_audio", "truncated_audio", "silent_audio",
    "wrong_duration", "wrong_format",
})
ERROR_MODES = frozenset({"temporary_failure", "permanent_failure", "rate_limited"})

_MIN_DURATION_S = 0.3


def _run_ffmpeg(args: List[str]) -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *args],
            check=True, capture_output=True, timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="replace")[-500:]
        raise RuntimeError(f"fake provider: ffmpeg failed: {tail}") from exc


class FakeSpeechProvider(SpeechProvider):
    """Deterministic offline TTS provider producing real MP3 audio."""

    name = "fake"
    display_name = "Fake (test)"
    max_chars = 100_000
    paid = False
    cost_per_million_chars = 0.0
    catalog_discoverable = False  # never appears in /api/providers or /api/voices

    # Process-wide memo: determinism makes this a pure cache. Keyed by
    # (mode, voice_id, salt, sha256(text)) → artifact bytes.
    _memo: Dict[Tuple[str, str, str, str], bytes] = {}

    def __init__(self) -> None:
        self.mode = "success"
        self.fail_after_n_calls: Optional[int] = None
        self.calls = 0
        self._temporarily_failed: set = set()

    # ------------------------------------------------------------------
    # SpeechProvider interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        return _VOICES

    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        return self._synthesize(text, voice_id)

    def synthesize_with_options(
        self, text: str, voice_id: str, engine: str = "neural", *,
        rate: Optional[str] = None, pitch: Optional[str] = None,
        volume: Optional[str] = None, style: Optional[str] = None,
    ) -> bytes:
        # Options participate in the digest so a directed render is audibly
        # (and byte-wise) different from a plain one — required for tests that
        # prove voice assignment/lexicon edits change the produced audio.
        if any(v is not None for v in (rate, pitch, volume, style)):
            salt = f"{rate}|{pitch}|{volume}|{style}"
        else:
            salt = ""
        return self._synthesize(text, voice_id, salt=salt)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _synthesize(self, text: str, voice_id: str, salt: str = "") -> bytes:
        self.calls += 1
        mode, clean = self._resolve_mode(text)

        if self.fail_after_n_calls is not None and self.calls > self.fail_after_n_calls:
            raise RuntimeError(
                f"fake provider: failing after {self.fail_after_n_calls} calls"
            )
        if mode == "permanent_failure":
            raise RuntimeError("fake provider: permanent failure")
        if mode == "rate_limited":
            raise RuntimeError("fake provider: rate limited")
        if mode == "temporary_failure":
            key = (voice_id, salt, clean)
            if key not in self._temporarily_failed:
                self._temporarily_failed.add(key)
                raise RuntimeError("fake provider: temporary failure (succeeds on retry)")
            mode = "success"

        return self._artifact(mode, clean, voice_id, salt)

    def _resolve_mode(self, text: str) -> Tuple[str, str]:
        m = _MARKER_RE.search(text)
        if m:
            mode = m.group(1)
            clean = _MARKER_RE.sub("", text)
        else:
            mode, clean = self.mode, text
        if mode not in ARTIFACT_MODES and mode not in ERROR_MODES:
            raise RuntimeError(f"fake provider: unknown mode {mode!r}")
        return mode, clean

    def _artifact(self, mode: str, clean: str, voice_id: str, salt: str) -> bytes:
        digest = hashlib.sha256(f"{voice_id}:{salt}:{clean}".encode()).digest()
        memo_key = (mode, voice_id, salt, digest.hex())
        cached = self._memo.get(memo_key)
        if cached is not None:
            return cached

        duration = max(len(clean) / CHARS_PER_SECOND, _MIN_DURATION_S)
        freq = 220 + ((digest[0] << 8 | digest[1]) % 440)

        if mode == "invalid_audio":
            # Plausible length for 64 kbps (~8000 B/s), deterministic
            # high-entropy garbage (chained sha256), no valid header.
            target = max(int(duration * 8000), 1024)
            chunks, seed, total = [], digest, 0
            while total < target:
                seed = hashlib.sha256(seed).digest()
                chunks.append(seed)
                total += len(seed)
            data = (b"\x00\x00\x00\x00" + b"".join(chunks))[:target]
        elif mode == "wrong_duration":
            wrong = duration * 8 if duration * 8 <= 300 else duration / 8
            data = self._sine_mp3(freq, wrong)
        elif mode == "silent_audio":
            data = self._silence_mp3(duration)
        elif mode == "wrong_format":
            data = self._sine_wav(freq, duration)
        elif mode == "truncated_audio":
            full = self._sine_mp3(freq, duration)
            data = full[: max(int(len(full) * 0.4), 512)]
        else:  # success
            data = self._sine_mp3(freq, duration)

        self._memo[memo_key] = data
        return data

    @staticmethod
    def _sine_mp3(freq: int, duration: float) -> bytes:
        return FakeSpeechProvider._render(
            ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration:.3f}",
             "-ac", "1", "-ar", "24000", "-b:a", "64k"], suffix=".mp3")

    @staticmethod
    def _silence_mp3(duration: float) -> bytes:
        return FakeSpeechProvider._render(
            ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", f"{duration:.3f}", "-b:a", "64k"], suffix=".mp3")

    @staticmethod
    def _sine_wav(freq: int, duration: float) -> bytes:
        return FakeSpeechProvider._render(
            ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration:.3f}",
             "-ac", "1", "-ar", "24000"], suffix=".wav")

    @staticmethod
    def _render(args: List[str], suffix: str) -> bytes:
        # Write to a real file, not a pipe: ffmpeg needs a seekable output to
        # finalize the MP3 Xing header, which the truncation-detection rule
        # (header duration vs. decoded duration) depends on.
        with tempfile.TemporaryDirectory(prefix="fake_tts_") as td:
            out = os.path.join(td, f"out{suffix}")
            _run_ffmpeg([*args, out])
            with open(out, "rb") as f:
                return f.read()
