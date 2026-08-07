"""
GPU Synthesis Worker for ACX City.

Handles TTS synthesis using self-hosted GPU models (Kokoro, Fish Speech, Chatterbox).
Routes requests to the appropriate synthesizer based on configuration, applies
prosody tags, voice cloning, multi-speaker chapter synthesis, and post-processing
(loudness normalization, de-essing, room tone).

Environment variables:
    GPU_MODEL           - Which synthesizer backend to use: "kokoro", "fish", "chatterbox"
    KOKORO_ENDPOINT     - HTTP endpoint for Kokoro model server (default: http://localhost:8080)
    FISH_SPEECH_ENDPOINT - HTTP endpoint for Fish Speech server (default: http://localhost:8081)
    CHATTERBOX_ENDPOINT - HTTP endpoint for Chatterbox server (default: http://localhost:8082)
    S3_ENDPOINT         - S3-compatible endpoint for loading speaker embeddings
    S3_BUCKET           - S3 bucket name for speaker embedding assets
"""

from __future__ import annotations

import io
import logging
import os
import re
import struct
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

try:
    import pyloudnorm
except ImportError:
    pyloudnorm = None  # type: ignore[assignment]

try:
    import soundfile as sf
except ImportError:
    sf = None  # type: ignore[assignment]

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 24000
LOUDNESS_METER_WINDOW_S = 5.0  # pyloudnorm momentary window
DE_ESS_CUTOFF_HZ = 6000.0
DE_ESS_RATIO = 0.3  # gain reduction ratio above cutoff
ROOM_TONE_FADE_MS = 50  # fade-in/out for room tone splice

# Prosody tag patterns
_PAUSE_RE = re.compile(r"\[pause:(\d+)\]")
_RATE_RE = re.compile(r"\[rate:(slow|fast)\]")
_EMPHASIS_RE = re.compile(r"\[emphasis\]")


class SynthesisError(Exception):
    """Raised when TTS synthesis fails."""


class VoiceCloneError(Exception):
    """Raised when voice cloning / embedding extraction fails."""


class UnsupportedModel(Exception):
    """Raised when an unknown GPU_MODEL value is configured."""


class ProsodyTag(Enum):
    """Parsed prosody tag types."""
    PAUSE = "pause"
    RATE = "rate"
    EMPHASIS = "emphasis"


@dataclass
class ProsodySegment:
    """A text segment with optional prosody modifications."""
    text: str
    pause_ms: Optional[int] = None
    rate: Optional[str] = None  # "slow" | "fast" | None
    emphasis: bool = False


@dataclass
class ChapterSegment:
    """A segment of a chapter, tagged with a character voice key."""
    text: str
    character_id: str
    prosody: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Prosody tag parsing
# ---------------------------------------------------------------------------


def parse_prosody_tags(text: str) -> List[ProsodySegment]:
    """
    Parse prosody control tags from synthesis text.

    Supported tags:
        [pause:NNN]   – insert NNN milliseconds of silence
        [rate:slow]   – slow down speech rate (~0.75x)
        [rate:fast]   – speed up speech rate (~1.25x)
        [emphasis]    – emphasize the immediately following word/phrase

    Tags are stripped from the text and their effects captured in ProsodySegment
    objects. Tags may appear anywhere; emphasis applies to the next word.

    Args:
        text: Raw text possibly containing prosody tags.

    Returns:
        List of ProsodySegment objects representing the tagged text.
    """
    segments: List[ProsodySegment] = []
    remaining = text

    while remaining:
        # Find earliest tag
        pause_m = _PAUSE_RE.search(remaining)
        rate_m = _RATE_RE.search(remaining)
        emphasis_m = _EMPHASIS_RE.search(remaining)

        matches = [
            (m, "pause") for m in ([pause_m] if pause_m else [])
        ] + [
            (m, "rate") for m in ([rate_m] if rate_m else [])
        ] + [
            (m, "emphasis") for m in ([emphasis_m] if emphasis_m else [])
        ]

        if not matches:
            # No more tags – remainder is plain text
            stripped = remaining.strip()
            if stripped:
                segments.append(ProsodySegment(text=stripped))
            break

        # Pick the earliest match
        matches.sort(key=lambda x: x[0].start())
        earliest, tag_type = matches[0]
        before = remaining[: earliest.start()].strip()

        if before:
            segments.append(ProsodySegment(text=before))

        if tag_type == "pause":
            ms = int(earliest.group(1))
            # Append a silent pause segment
            segments.append(ProsodySegment(text="", pause_ms=ms))
        elif tag_type == "rate":
            rate_val = earliest.group(1)
            # Rate applies to the next word(s); create a marker segment
            segments.append(ProsodySegment(text="", rate=rate_val))
        elif tag_type == "emphasis":
            segments.append(ProsodySegment(text="", emphasis=True))

        remaining = remaining[earliest.end():]

    return segments


# ---------------------------------------------------------------------------
# Abstract base synthesizer
# ---------------------------------------------------------------------------


class BaseSynthesizer(ABC):
    """Abstract base class for GPU TTS synthesizers."""

    def __init__(self, endpoint: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.sample_rate = sample_rate
        self._session: Optional["requests.Session"] = None
        logger.info(
            "%s initialized – endpoint=%s sample_rate=%d",
            self.__class__.__name__,
            self.endpoint,
            self.sample_rate,
        )

    @property
    def session(self) -> "requests.Session":
        """Lazy-initialised requests session with connection pooling."""
        if self._session is None:
            if requests is None:
                raise ImportError("requests is required for HTTP synthesis calls")
            self._session = requests.Session()
            self._session.headers.update({"Content-Type": "application/json"})
        return self._session

    def _post(self, path: str, payload: Dict[str, Any], timeout: float = 120.0) -> "requests.Response":
        """Send a POST request to the model server and return the response."""
        url = f"{self.endpoint}{path}"
        try:
            resp = self.session.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.ConnectionError as exc:
            raise SynthesisError(f"Cannot reach {self.__class__.__name__} at {url}: {exc}") from exc
        except requests.Timeout as exc:
            raise SynthesisError(f"Request to {url} timed out after {timeout}s: {exc}") from exc
        except requests.HTTPError as exc:
            raise SynthesisError(
                f"{self.__class__.__name__} returned {resp.status_code}: {resp.text[:500]}"
            ) from exc

    @abstractmethod
    def synthesize(self, text: str, **kwargs: Any) -> np.ndarray:
        """
        Synthesize speech from text.

        Args:
            text: Input text to synthesize.

        Returns:
            numpy array of audio samples (float32, mono, at self.sample_rate).
        """
        ...


# ---------------------------------------------------------------------------
# Kokoro TTS Synthesizer
# ---------------------------------------------------------------------------


class KokoroSynthesizer(BaseSynthesizer):
    """
    Synthesizer backed by a self-hosted Kokoro TTS model.

    Supports prosody tags: [pause:NNN], [rate:slow/fast], [emphasis].

    Usage::

        synth = KokoroSynthesizer("http://gpu-host:8080")
        embedding = synth.load_speaker_embedding("speakers/alice.pt")
        audio = synth.synthesize("Hello [pause:300] world.", voice_tensor=embedding)
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        endpoint = endpoint or os.getenv("KOKORO_ENDPOINT", "http://localhost:8080")
        super().__init__(endpoint, sample_rate)

    def load_speaker_embedding(self, latent_s3_key: str) -> np.ndarray:
        """
        Load a pre-computed speaker embedding from S3 storage.

        The embedding is expected to be a numpy `.npz` or raw float32 array
        stored under the given S3 key.

        Args:
            latent_s3_key: S3 object key (e.g. "speakers/alice_latent.npz").

        Returns:
            Speaker embedding as a numpy float32 array.

        Raises:
            VoiceCloneError: If the embedding cannot be loaded.
        """
        s3_endpoint = os.getenv("S3_ENDPOINT", "")
        s3_bucket = os.getenv("S3_BUCKET", "acx-voices")

        if not s3_endpoint or boto3 is None:
            logger.warning(
                "S3 not configured or boto3 missing – attempting local fallback for '%s'",
                latent_s3_key,
            )
            return self._load_embedding_local(latent_s3_key)

        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=s3_endpoint,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            )
            buf = io.BytesIO()
            s3.download_fileobj(s3_bucket, latent_s3_key, buf)
            buf.seek(0)

            if latent_s3_key.endswith(".npz"):
                data = np.load(buf)
                # Return the first (or only) array in the archive
                key = data.files[0]
                embedding = data[key].astype(np.float32)
            else:
                embedding = np.frombuffer(buf.read(), dtype=np.float32)

            logger.info(
                "Loaded speaker embedding from s3://%s/%s – shape=%s",
                s3_bucket,
                latent_s3_key,
                embedding.shape,
            )
            return embedding
        except Exception as exc:
            raise VoiceCloneError(
                f"Failed to load speaker embedding '{latent_s3_key}': {exc}"
            ) from exc

    def _load_embedding_local(self, path: str) -> np.ndarray:
        """Fallback: load embedding from a local file path."""
        try:
            if path.endswith(".npz"):
                data = np.load(path)
                return data[data.files[0]].astype(np.float32)
            return np.fromfile(path, dtype=np.float32)
        except Exception as exc:
            raise VoiceCloneError(f"Local embedding load failed for '{path}': {exc}") from exc

    def synthesize(
        self,
        text: str,
        voice_tensor: Optional[np.ndarray] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        **kwargs: Any,
    ) -> np.ndarray:
        """
        Synthesize speech from text with prosody control.

        Args:
            text: Input text. May contain prosody tags [pause:NNN], [rate:slow/fast],
                  [emphasis].
            voice_tensor: Speaker embedding array. If None, uses the model default.
            sample_rate: Desired output sample rate (default 24000).

        Returns:
            Audio samples as float32 numpy array, shape (num_samples,).

        Raises:
            SynthesisError: On synthesis failure.
        """
        segments = parse_prosody_tags(text)
        audio_chunks: List[np.ndarray] = []

        for seg in segments:
            # Handle silent pauses
            if seg.pause_ms is not None:
                silence = np.zeros(
                    int(sample_rate * seg.pause_ms / 1000.0), dtype=np.float32
                )
                audio_chunks.append(silence)
                continue

            # Skip empty marker segments (rate/emphasis markers without text)
            if not seg.text.strip():
                continue

            payload: Dict[str, Any] = {
                "text": seg.text,
                "sample_rate": sample_rate,
            }
            if voice_tensor is not None:
                payload["speaker_embedding"] = voice_tensor.tolist()
            if seg.rate:
                payload["rate"] = seg.rate
            if seg.emphasis:
                payload["emphasis"] = True

            try:
                resp = self._post("/synthesize", payload)
                audio = self._decode_audio_response(resp, sample_rate)
                audio_chunks.append(audio)
            except SynthesisError:
                raise
            except Exception as exc:
                raise SynthesisError(f"Kokoro synthesis failed for segment '{seg.text[:60]}': {exc}") from exc

        if not audio_chunks:
            logger.warning("Kokoro: all segments were empty – returning silence")
            return np.zeros(int(sample_rate * 0.1), dtype=np.float32)

        return np.concatenate(audio_chunks)

    @staticmethod
    def _decode_audio_response(resp: "requests.Response", sample_rate: int) -> np.ndarray:
        """Decode an audio response (WAV bytes or raw float32) into a numpy array."""
        content_type = resp.headers.get("Content-Type", "")

        if "audio/wav" in content_type or "audio/x-wav" in content_type:
            if sf is None:
                raise SynthesisError("soundfile is required to decode WAV responses")
            audio, sr = sf.read(io.BytesIO(resp.content), dtype="float32")
            if sr != sample_rate:
                # Simple resample via linear interpolation
                duration = len(audio) / sr
                target_len = int(duration * sample_rate)
                audio = np.interp(
                    np.linspace(0, len(audio), target_len, endpoint=False),
                    np.arange(len(audio)),
                    audio,
                ).astype(np.float32)
            return audio

        # Assume raw float32 PCM
        return np.frombuffer(resp.content, dtype=np.float32).copy()


# ---------------------------------------------------------------------------
# Fish Speech Synthesizer
# ---------------------------------------------------------------------------


class FishSpeechSynthesizer(BaseSynthesizer):
    """
    Synthesizer backed by Fish Speech (open-source zero-shot TTS).

    Supports voice cloning from a 10-30 s reference audio clip.  The server
    returns a 512-dimensional speaker embedding that can be reused.

    Usage::

        synth = FishSpeechSynthesizer()
        embedding = synth.clone_voice(open("ref.wav", "rb").read())
        audio = synth.synthesize("Hello world.", voice_id="narrator_1")
    """

    EMBEDDING_DIM = 512

    def __init__(
        self,
        endpoint: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        endpoint = endpoint or os.getenv("FISH_SPEECH_ENDPOINT", "http://localhost:8081")
        super().__init__(endpoint, sample_rate)

    def clone_voice(self, reference_audio_bytes: bytes) -> np.ndarray:
        """
        Extract a speaker embedding from a reference audio clip.

        The reference audio should be 10-30 seconds of clean speech.  The server
        runs its encoder and returns a 512-dimensional float32 vector.

        Args:
            reference_audio_bytes: Raw audio bytes (WAV/FLAC/MP3).

        Returns:
            512-dimensional float32 numpy array representing the speaker voice.

        Raises:
            VoiceCloneError: If cloning fails.
        """
        if not reference_audio_bytes:
            raise VoiceCloneError("reference_audio_bytes must not be empty")

        url = f"{self.endpoint}/clone_voice"
        try:
            resp = self.session.post(
                url,
                files={"audio": ("reference.wav", reference_audio_bytes, "audio/wav")},
                timeout=60,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise VoiceCloneError(f"Fish Speech voice cloning request failed: {exc}") from exc

        try:
            data = resp.json()
            embedding = np.array(data["embedding"], dtype=np.float32)
        except (KeyError, ValueError) as exc:
            # Fallback: try raw binary response
            embedding = np.frombuffer(resp.content, dtype=np.float32).copy()

        if embedding.ndim != 1 or embedding.shape[0] != self.EMBEDDING_DIM:
            raise VoiceCloneError(
                f"Expected {self.EMBEDDING_DIM}-dim embedding, got shape {embedding.shape}"
            )

        logger.info("Fish Speech voice clone complete – embedding shape=%s", embedding.shape)
        return embedding

    def synthesize(
        self,
        text: str,
        reference_audio: Optional[bytes] = None,
        voice_id: Optional[str] = None,
        **kwargs: Any,
    ) -> np.ndarray:
        """
        Synthesize speech using Fish Speech.

        Provide either ``reference_audio`` (raw bytes for zero-shot cloning) or
        ``voice_id`` (a pre-registered speaker identifier on the server).

        Args:
            text: Text to speak.
            reference_audio: Optional raw audio bytes for zero-shot voice cloning.
            voice_id: Optional pre-registered speaker ID.

        Returns:
            Audio samples as float32 numpy array, shape (num_samples,).

        Raises:
            SynthesisError: On synthesis failure.
            ValueError: If neither reference_audio nor voice_id is provided.
        """
        if not text.strip():
            return np.zeros(int(self.sample_rate * 0.1), dtype=np.float32)

        if reference_audio is None and voice_id is None:
            raise ValueError("Either reference_audio or voice_id must be provided")

        # Build multipart request
        url = f"{self.endpoint}/synthesize"
        files: Dict[str, Any] = {"text": (None, text)}

        if reference_audio is not None:
            files["reference_audio"] = ("reference.wav", reference_audio, "audio/wav")
        if voice_id is not None:
            files["voice_id"] = (None, voice_id)

        try:
            resp = self.session.post(url, files=files, timeout=120)
            resp.raise_for_status()
        except Exception as exc:
            raise SynthesisError(f"Fish Speech synthesis request failed: {exc}") from exc

        return KokoroSynthesizer._decode_audio_response(resp, self.sample_rate)


# ---------------------------------------------------------------------------
# Chatterbox Synthesizer
# ---------------------------------------------------------------------------


class ChatterboxSynthesizer(BaseSynthesizer):
    """
    Synthesizer backed by Chatterbox TTS.

    Supports emotion-conditioned synthesis with configurable voice parameters.

    Usage::

        synth = ChatterboxSynthesizer()
        audio = synth.synthesize(
            "I can't believe this happened!",
            voice_params={"pitch_shift": 2, "breathiness": 0.3},
            emotion="surprise",
        )
    """

    SUPPORTED_EMOTIONS = (
        "neutral",
        "happy",
        "sad",
        "angry",
        "surprise",
        "fear",
        "disgust",
        "contempt",
    )

    def __init__(
        self,
        endpoint: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        endpoint = endpoint or os.getenv("CHATTERBOX_ENDPOINT", "http://localhost:8082")
        super().__init__(endpoint, sample_rate)

    def synthesize(
        self,
        text: str,
        voice_params: Optional[Dict[str, Any]] = None,
        emotion: str = "neutral",
        **kwargs: Any,
    ) -> np.ndarray:
        """
        Synthesize speech with emotion conditioning.

        Args:
            text: Text to synthesize.
            voice_params: Voice configuration dict. Recognised keys:
                - ``pitch_shift`` (int): Semitones to shift pitch.
                - ``speed`` (float): Speaking rate multiplier (0.5 – 2.0).
                - ``breathiness`` (float): 0.0 – 1.0 breathiness amount.
                - ``roughness`` (float): 0.0 – 1.0 vocal roughness.
                - ``speaker_embedding`` (list[float]): Pre-computed speaker vector.
            emotion: One of neutral, happy, sad, angry, surprise, fear, disgust, contempt.

        Returns:
            Audio samples as float32 numpy array, shape (num_samples,).

        Raises:
            SynthesisError: On synthesis failure.
            ValueError: On invalid emotion.
        """
        if emotion not in self.SUPPORTED_EMOTIONS:
            raise ValueError(
                f"Unsupported emotion '{emotion}'. "
                f"Choose from: {', '.join(self.SUPPORTED_EMOTIONS)}"
            )

        if not text.strip():
            return np.zeros(int(self.sample_rate * 0.1), dtype=np.float32)

        payload: Dict[str, Any] = {
            "text": text,
            "emotion": emotion,
            "sample_rate": self.sample_rate,
        }
        if voice_params:
            payload.update(voice_params)

        try:
            resp = self._post("/synthesize", payload)
        except SynthesisError:
            raise
        except Exception as exc:
            raise SynthesisError(f"Chatterbox synthesis failed: {exc}") from exc

        return KokoroSynthesizer._decode_audio_response(resp, self.sample_rate)


# ---------------------------------------------------------------------------
# Synthesis Router
# ---------------------------------------------------------------------------


class SynthesisRouter:
    """
    Routes synthesis requests to the correct GPU-backed synthesizer.

    The active synthesizer is selected via the ``GPU_MODEL`` environment
    variable (one of ``kokoro``, ``fish``, ``chatterbox``).

    For multi-speaker chapter synthesis, pass a character→voice map and a list
    of ``ChapterSegment`` objects; the router will concatenate per-segment audio
    with short inter-segment pauses.

    Usage::

        router = SynthesisRouter()
        chapter_audio = router.synthesize_chapter(
            segments=[
                ChapterSegment("Hello there.", "narrator"),
                ChapterSegment("Hi!", "alice"),
            ],
            character_voice_map={
                "narrator": {"voice_id": "narrator_1"},
                "alice": {"voice_tensor": alice_embedding},
            },
        )
    """

    INTER_SEGMENT_PAUSE_S = 0.35  # silence between character turns

    def __init__(self) -> None:
        model_name = os.getenv("GPU_MODEL", "kokoro").lower().strip()
        self._synthesizer = self._create_synthesizer(model_name)
        self._model_name = model_name
        logger.info("SynthesisRouter active model: %s", model_name)

    @staticmethod
    def _create_synthesizer(name: str) -> BaseSynthesizer:
        """Instantiate the synthesizer matching the given model name."""
        if name == "kokoro":
            return KokoroSynthesizer()
        elif name in ("fish", "fish_speech", "fishspeech"):
            return FishSpeechSynthesizer()
        elif name in ("chatterbox", "chatter_box"):
            return ChatterboxSynthesizer()
        else:
            raise UnsupportedModel(
                f"Unknown GPU_MODEL '{name}'. "
                f"Supported: kokoro, fish, chatterbox"
            )

    @property
    def synthesizer(self) -> BaseSynthesizer:
        """The currently active synthesizer instance."""
        return self._synthesizer

    @property
    def model_name(self) -> str:
        """Lowercase name of the active model."""
        return self._model_name

    def synthesize(self, text: str, **kwargs: Any) -> np.ndarray:
        """
        Synthesize a single text segment using the active synthesizer.

        Args:
            text: Text to synthesize.
            **kwargs: Forwarded to the underlying synthesizer.

        Returns:
            Audio samples as float32 numpy array.
        """
        return self._synthesizer.synthesize(text, **kwargs)

    def synthesize_chapter(
        self,
        segments: Sequence[ChapterSegment],
        character_voice_map: Dict[str, Dict[str, Any]],
    ) -> np.ndarray:
        """
        Synthesize a full chapter with multiple speakers.

        Each segment is synthesized with the voice parameters of its assigned
        character.  Short pauses are inserted between consecutive segments
        (longer if the speaker changes).

        Args:
            segments: Ordered list of ChapterSegment objects.
            character_voice_map: Mapping of character_id → voice parameters dict.
                Keys depend on the active synthesizer:
                - Kokoro: ``voice_tensor`` (np.ndarray), optionally ``sample_rate``
                - Fish:   ``voice_id`` (str) or ``reference_audio`` (bytes)
                - Chatterbox: ``voice_params`` (dict), optionally ``emotion``

        Returns:
            Concatenated chapter audio as float32 numpy array.

        Raises:
            SynthesisError: If any segment fails.
            ValueError: If a segment references an unknown character_id.
        """
        if not segments:
            logger.warning("synthesize_chapter called with empty segments")
            return np.array([], dtype=np.float32)

        sample_rate = self._synthesizer.sample_rate
        chunks: List[np.ndarray] = []
        prev_character: Optional[str] = None

        for idx, seg in enumerate(segments):
            if seg.character_id not in character_voice_map:
                raise ValueError(
                    f"Segment {idx} references unknown character_id '{seg.character_id}'. "
                    f"Known: {list(character_voice_map.keys())}"
                )

            voice_cfg = character_voice_map[seg.character_id]

            # Inter-segment pause
            if chunks:
                if seg.character_id != prev_character:
                    # Longer pause when speaker changes
                    pause_s = self.INTER_SEGMENT_PAUSE_S * 2
                else:
                    pause_s = self.INTER_SEGMENT_PAUSE_S
                pause = np.zeros(int(sample_rate * pause_s), dtype=np.float32)
                chunks.append(pause)

            # Merge prosody from segment into text if present
            synthesis_text = self._apply_segment_prosody(seg)

            try:
                audio = self._synthesizer.synthesize(synthesis_text, **voice_cfg)
                chunks.append(audio)
            except Exception as exc:
                raise SynthesisError(
                    f"Chapter segment {idx} ('{seg.text[:40]}…') failed: {exc}"
                ) from exc

            prev_character = seg.character_id

        result = np.concatenate(chunks)
        logger.info(
            "Chapter synthesis complete – %d segments, %.1f s audio",
            len(segments),
            len(result) / sample_rate,
        )
        return result

    @staticmethod
    def _apply_segment_prosody(seg: ChapterSegment) -> str:
        """
        Inject prosody tags into the segment text based on its prosody dict.

        Args:
            seg: A ChapterSegment with optional prosody overrides.

        Returns:
            Text string with prosody tags prepended as needed.
        """
        if not seg.prosody:
            return seg.text

        tags = ""
        if "pause_before" in seg.prosody:
            tags += f"[pause:{int(seg.prosody['pause_before'])}]"
        if "rate" in seg.prosody:
            tags += f"[rate:{seg.prosody['rate']}]"
        if seg.prosody.get("emphasis"):
            tags += "[emphasis]"

        return f"{tags}{seg.text}" if tags else seg.text


# ---------------------------------------------------------------------------
# Post-processing utilities
# ---------------------------------------------------------------------------


def normalize_loudness(
    audio: np.ndarray,
    target_lufs: float = -23.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """
    Normalize audio to a target integrated loudness (LUFS) per ITU-R BS.1770.

    Uses pyloudnorm for measurement and applies a linear gain to hit the target.

    Args:
        audio: Input audio samples (float32 or float64, mono).
        target_lufs: Desired integrated loudness in LUFS (default -23.0, ACX standard).
        sample_rate: Audio sample rate in Hz.

    Returns:
        Loudness-normalized audio as float32 array.

    Raises:
        ImportError: If pyloudnorm is not installed.
        ValueError: If audio is empty.
    """
    if pyloudnorm is None:
        raise ImportError("pyloudnorm is required for loudness normalization (pip install pyloudnorm)")

    audio = np.asarray(audio, dtype=np.float64)

    if audio.size == 0:
        raise ValueError("Cannot normalize loudness of empty audio")

    meter = pyloudnorm.Meter(sample_rate)
    current_lufs = meter.integrated_loudness(audio)

    if np.isinf(current_lufs):
        logger.warning("Audio is silent – skipping loudness normalization")
        return audio.astype(np.float32)

    gain_db = target_lufs - current_lufs
    gain_linear = 10.0 ** (gain_db / 20.0)

    normalized = audio * gain_linear

    # Soft-clip to prevent overshooting ±1.0
    peak = np.max(np.abs(normalized))
    if peak > 1.0:
        normalized = np.tanh(normalized)  # gentle saturation
        logger.info("Applied tanh soft-clip (peak was %.2f)", peak)

    result = normalized.astype(np.float32)
    logger.debug(
        "Loudness normalization: %.1f → %.1f LUFS (gain %.1f dB)",
        current_lufs,
        target_lufs,
        gain_db,
    )
    return result


def de_ess(
    audio: np.ndarray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    cutoff_hz: float = DE_ESS_CUTOFF_HZ,
    ratio: float = DE_ESS_RATIO,
) -> np.ndarray:
    """
    De-ess audio by attenuating sibilant frequencies above a cutoff.

    Applies a simple spectral split: frequencies above ``cutoff_hz`` are
    attenuated by ``ratio`` (0.0 = full suppression, 1.0 = no change).

    Args:
        audio: Input audio samples (float32, mono).
        sample_rate: Audio sample rate in Hz.
        cutoff_hz: Frequency above which to attenuate sibilants (default 6000 Hz).
        ratio: Gain factor for sibilant band (default 0.3).

    Returns:
        De-essed audio as float32 array.
    """
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size == 0:
        return audio

    # FFT-based spectral split
    n = len(audio)
    spectrum = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    # Create a mask: below cutoff = 1.0, above cutoff = ratio
    mask = np.ones_like(freqs)
    sibilant_idx = freqs >= cutoff_hz
    mask[sibilant_idx] = ratio

    # Apply smooth transition over 500 Hz around cutoff
    transition_width = 500.0
    transition_idx = (freqs >= cutoff_hz - transition_width) & (freqs < cutoff_hz)
    if np.any(transition_idx):
        transition_pos = (freqs[transition_idx] - (cutoff_hz - transition_width)) / transition_width
        mask[transition_idx] = 1.0 - transition_pos * (1.0 - ratio)

    filtered_spectrum = spectrum * mask
    result = np.fft.irfft(filtered_spectrum, n=n).astype(np.float32)

    logger.debug("De-ess applied: cutoff=%.0f Hz, ratio=%.2f", cutoff_hz, ratio)
    return result


def add_room_tone(
    audio: np.ndarray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    duration_s: float = 0.5,
    noise_level: float = -60.0,
) -> np.ndarray:
    """
    Pad audio with low-level room tone at the start and end.

    Room tone is generated as shaped pink-ish noise at the specified level
    below 0 dBFS, faded in/out to avoid clicks.  This prevents dead-silence
    gaps that can cause listener fatigue in audiobook production.

    Args:
        audio: Input audio samples (float32, mono).
        sample_rate: Audio sample rate in Hz.
        duration_s: Duration of room tone padding on each side (default 0.5 s).
        noise_level: Room tone level in dBFS (default -60.0).

    Returns:
        Audio with room tone prepended and appended, as float32 array.
    """
    audio = np.asarray(audio, dtype=np.float32)

    num_pad = int(sample_rate * duration_s)
    if num_pad == 0:
        return audio

    # Generate shaped noise (pink-ish via filtering white noise)
    rng = np.random.default_rng()
    white = rng.standard_normal(num_pad).astype(np.float32)

    # Simple pink noise approximation: integrate white noise spectrum then normalize
    # (Voss-McCartney style would be ideal; simple IIR fallback here)
    pink = np.cumsum(white)
    pink = pink - np.mean(pink)
    pink = pink / (np.max(np.abs(pink)) + 1e-10)

    # Scale to target level
    linear_level = 10.0 ** (noise_level / 20.0)
    room_tone = pink * linear_level

    # Apply fade-in / fade-out
    fade_samples = min(int(sample_rate * ROOM_TONE_FADE_MS / 1000.0), num_pad // 2)
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)

    room_tone[:fade_samples] *= fade_in
    room_tone[-fade_samples:] *= fade_out

    result = np.concatenate([room_tone, audio, room_tone.copy()])
    logger.debug(
        "Room tone added: %.1f s padding each side, level=%.0f dBFS",
        duration_s,
        noise_level,
    )
    return result


# ---------------------------------------------------------------------------
# Convenience: full pipeline
# ---------------------------------------------------------------------------


def synthesize_with_postprocessing(
    text: str,
    character_voice_map: Optional[Dict[str, Dict[str, Any]]] = None,
    target_lufs: float = -23.0,
    apply_de_ess: bool = True,
    apply_room_tone: bool = True,
    room_tone_s: float = 0.5,
) -> np.ndarray:
    """
    High-level convenience: synthesize text through the router then apply
    full post-processing (loudness normalization, de-essing, room tone).

    For single-speaker use.  For multi-speaker chapters, use
    ``SynthesisRouter.synthesize_chapter`` directly and call post-processing
    functions individually.

    Args:
        text: Text to synthesize.
        character_voice_map: Voice parameters for the single character (passed as kwargs).
        target_lufs: Target loudness (default -23.0 LUFS, ACX spec).
        apply_de_ess: Whether to de-ess the output.
        apply_room_tone: Whether to add room tone padding.
        room_tone_s: Room tone duration per side in seconds.

    Returns:
        Fully processed audio as float32 numpy array.
    """
    router = SynthesisRouter()
    voice_kwargs = list(character_voice_map.values())[0] if character_voice_map else {}
    audio = router.synthesize(text, **voice_kwargs)

    audio = normalize_loudness(audio, target_lufs=target_lufs, sample_rate=router.synthesizer.sample_rate)

    if apply_de_ess:
        audio = de_ess(audio, sample_rate=router.synthesizer.sample_rate)

    if apply_room_tone:
        audio = add_room_tone(audio, sample_rate=router.synthesizer.sample_rate, duration_s=room_tone_s)

    return audio
