"""
Waveform peak data generator for WaveSurfer.js visualization.

Generates normalized peak arrays from audio files or numpy arrays,
plus metadata for speaker segments and QC markers. Also supports
M4B chapter metadata generation for FFmpeg.
"""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from pydub import AudioSegment


def generate_peaks(audio_path: str, samples_per_second: int = 100) -> list[float]:
    """Read an audio file and return peak amplitude values normalized to 0.0–1.0.

    The audio is downsampled so that one peak value is produced for every
    ``samples_per_second`` seconds of audio (default 100, i.e. ~10 ms
    resolution, which is standard for WaveSurfer.js).

    Args:
        audio_path: Path to any audio format supported by pydub/ffmpeg.
        samples_per_second: Number of peak samples to produce per second
            of audio.  Higher values give finer waveform detail.

    Returns:
        List of floats in [0.0, 1.0] representing peak amplitudes.

    Raises:
        FileNotFoundError: If *audio_path* does not exist.
        RuntimeError: If the file cannot be decoded.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    audio = AudioSegment.from_file(str(path))
    return _peaks_from_audiosegment(audio, samples_per_second)


def generate_peaks_from_array(
    audio: np.ndarray,
    sample_rate: int,
    samples_per_second: int = 100,
) -> list[float]:
    """Generate peak data from a raw numpy audio array.

    Args:
        audio: 1-D numpy array of audio samples (float or int).
            If multi-dimensional, the channels are averaged first.
        sample_rate: Sample rate of the array (Hz).
        samples_per_second: Number of peak values per second of audio.

    Returns:
        List of floats in [0.0, 1.0].
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Convert to float64 in [-1, 1] range if needed
    if np.issubdtype(audio.dtype, np.integer):
        max_val = np.iinfo(audio.dtype).max
        audio = audio.astype(np.float64) / max_val
    else:
        audio = audio.astype(np.float64)

    total_samples = len(audio)
    samples_per_chunk = max(1, sample_rate // samples_per_second)
    num_chunks = max(1, total_samples // samples_per_chunk)

    peaks: list[float] = []
    for i in range(num_chunks):
        start = i * samples_per_chunk
        end = min(start + samples_per_chunk, total_samples)
        chunk = audio[start:end]
        peak = float(np.max(np.abs(chunk)))
        peaks.append(min(peak, 1.0))

    return peaks


def generate_waveform_json(
    audio_path: str,
    chapter_number: int,
    speaker_segments: Optional[list[dict]] = None,
) -> dict:
    """Generate a full waveform JSON object for WaveSurfer.js.

    The returned dict contains:

    - ``peaks``: normalized peak array
    - ``duration``: audio duration in seconds
    - ``sample_rate``: source sample rate
    - ``chapter_number``: chapter identifier
    - ``speaker_changes``: list of ``{time, speaker}`` markers derived
      from *speaker_segments*
    - ``qc_markers``: list of ``{time, type, detail}`` markers for
      silence / clipping issues detected in the audio

    Args:
        audio_path: Path to audio file.
        chapter_number: Chapter number (1-based).
        speaker_segments: Optional list of speaker diarization segments.
            Each dict should have ``start`` (seconds), ``end`` (seconds),
            and ``speaker`` (str) keys.

    Returns:
        Dict ready to be serialized as JSON.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    audio_seg = AudioSegment.from_file(str(path))
    duration = len(audio_seg) / 1000.0
    sample_rate = audio_seg.frame_rate

    peaks = _peaks_from_audiosegment(audio_seg, samples_per_second=100)

    # Speaker change markers
    speaker_changes: list[dict] = []
    if speaker_segments:
        prev_speaker: Optional[str] = None
        for seg in speaker_segments:
            spk = seg.get("speaker", "")
            if spk != prev_speaker:
                speaker_changes.append(
                    {"time": seg["start"], "speaker": spk}
                )
                prev_speaker = spk

    # QC markers: silence and clipping detection
    qc_markers = _detect_qc_issues(audio_seg)

    return {
        "chapter_number": chapter_number,
        "duration": round(duration, 3),
        "sample_rate": sample_rate,
        "peaks": peaks,
        "speaker_changes": speaker_changes,
        "qc_markers": qc_markers,
    }


def generate_m4b_chapters(
    chapter_durations: list[float],
    chapter_titles: list[str],
) -> str:
    """Generate an FFmpeg ``chapters.txt`` metadata file for M4B embedding.

    The output follows the FFmpeg metadata format and can be used with::

        ffmpeg -i input.m4b -i chapters.txt -map_metadata 1 -codec copy output.m4b

    Args:
        chapter_durations: Duration of each chapter in seconds.
        chapter_titles: Title for each chapter.  Must be the same length
            as *chapter_durations*.

    Returns:
        String content of the chapters metadata file.

    Raises:
        ValueError: If the two lists have different lengths.
    """
    if len(chapter_durations) != len(chapter_titles):
        raise ValueError(
            f"Length mismatch: {len(chapter_durations)} durations vs "
            f"{len(chapter_titles)} titles"
        )

    lines: list[str] = []
    current_start = 0.0

    for i, (dur, title) in enumerate(zip(chapter_durations, chapter_titles)):
        start_ms = int(round(current_start * 1000))
        end_ms = int(round((current_start + dur) * 1000))

        lines.append(f"[CHAPTER]")
        lines.append(f"TIMEBASE=1/1000")
        lines.append(f"START={start_ms}")
        lines.append(f"END={end_ms}")
        lines.append(f"title={title}")
        lines.append("")

        current_start += dur

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _peaks_from_audiosegment(
    audio: AudioSegment,
    samples_per_second: int = 100,
) -> list[float]:
    """Extract normalised peak values from a pydub AudioSegment."""
    samples = audio.get_array_of_samples()
    sample_rate = audio.frame_rate
    samples_per_chunk = max(1, sample_rate // samples_per_second)

    # Determine normalization denominator
    max_possible = float(2 ** (audio.sample_width * 8 - 1))

    peaks: list[float] = []
    for i in range(0, len(samples), samples_per_chunk):
        chunk = samples[i : i + samples_per_chunk]
        peak = max(abs(s) for s in chunk) / max_possible
        peaks.append(min(peak, 1.0))

    return peaks


def _detect_qc_issues(
    audio: AudioSegment,
    silence_threshold_db: float = -50.0,
    silence_min_duration_ms: int = 1000,
    clip_threshold: float = 0.99,
    samples_per_second: int = 100,
) -> list[dict]:
    """Detect silence and clipping in an AudioSegment.

    Returns a list of marker dicts with ``time``, ``type``, and ``detail``
    keys.  ``type`` is ``"silence"`` or ``"clipping"``.
    """
    markers: list[dict] = []

    # --- Silence detection via dBFS windows ---
    window_ms = 200
    total_ms = len(audio)
    silence_start: Optional[int] = None

    for t in range(0, total_ms, window_ms):
        window = audio[t : t + window_ms]
        if window.dBFS == float("-inf") or window.dBFS < silence_threshold_db:
            if silence_start is None:
                silence_start = t
        else:
            if silence_start is not None:
                duration = t - silence_start
                if duration >= silence_min_duration_ms:
                    markers.append(
                        {
                            "time": round(silence_start / 1000.0, 3),
                            "type": "silence",
                            "detail": f"{duration}ms below {silence_threshold_db}dBFS",
                        }
                    )
                silence_start = None

    # Flush trailing silence
    if silence_start is not None:
        duration = total_ms - silence_start
        if duration >= silence_min_duration_ms:
            markers.append(
                {
                    "time": round(silence_start / 1000.0, 3),
                    "type": "silence",
                    "detail": f"{duration}ms below {silence_threshold_db}dBFS",
                }
            )

    # --- Clipping detection ---
    samples = audio.get_array_of_samples()
    max_possible = float(2 ** (audio.sample_width * 8 - 1))
    clip_level = clip_threshold * max_possible
    sample_rate = audio.frame_rate
    samples_per_chunk = max(1, sample_rate // samples_per_second)

    for i in range(0, len(samples), samples_per_chunk):
        chunk = samples[i : i + samples_per_chunk]
        if any(abs(s) >= clip_level for s in chunk):
            markers.append(
                {
                    "time": round(i / sample_rate, 3),
                    "type": "clipping",
                    "detail": f"Amplitude >= {clip_threshold}",
                }
            )

    return markers
