"""
ACX/Audible Compliance Checking Module.

Checks audio files against ACX submission specifications:
  - Loudness (LUFS) targeting -23 LUFS ± tolerance
  - Peak level (dBFS) must be below -3 dBFS
  - Noise floor must be below -60 dBFS
  - Room tone at head/tail of chapters

Uses pyloudnorm for LUFS measurement and FFmpeg (via subprocess)
for peak and noise floor analysis.
"""

import json
import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import pyloudnorm
    import soundfile as sf
except ImportError:
    pyloudnorm = None
    sf = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    WARNING = "warning"
    BLOCK = "block"


@dataclass(frozen=True)
class ACXSpec:
    """ACX / Audible technical specification constants."""

    # Loudness
    TARGET_LUFS: float = -23.0
    LUFS_TOLERANCE: float = 1.0       # ±1 LUFS = pass
    LUFS_WARN: float = 2.0            # ±2 LUFS = warning
    LUFS_BLOCK: float = 3.0           # ±3+ LUFS = block

    # Peak
    PEAK_MAX_DBFS: float = -3.0
    PEAK_WARN_DBFS: float = -2.0
    PEAK_BLOCK_DBFS: float = -1.0

    # Noise floor
    NOISE_FLOOR_DBFS: float = -60.0
    NOISE_WARN_DBFS: float = -58.0
    NOISE_BLOCK_DBFS: float = -55.0

    # Room tone
    ROOM_TONE_MIN_S: float = 0.5
    ROOM_TONE_MAX_S: float = 1.0


SPEC = ACXSpec()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ACXCheck:
    """Single compliance check result."""
    check_name: str
    value: float
    threshold: float
    passed: bool
    severity: Optional[Severity] = None   # None when passed
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "value": round(self.value, 2),
            "threshold": round(self.threshold, 2),
            "passed": self.passed,
            "severity": self.severity.value if self.severity else None,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_ffmpeg_json(input_path: str, filtergraph: str) -> dict:
    """
    Run an FFmpeg command that outputs JSON to a temp file via
    the ``astats`` or ``volumedetect`` filter, and parse the result.

    Returns the parsed JSON dict, or raises on failure.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin",
        "-i", input_path,
        "-af", filtergraph,
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found – please install FFmpeg")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out processing {input_path}")

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (rc={result.returncode}): {result.stderr[:500]}"
        )
    return result.stderr


def _parse_peak_from_volumedetect(stderr: str) -> Optional[float]:
    """Extract max_volume dB from volumedetect output."""
    for line in stderr.splitlines():
        if "max_volume" in line:
            # e.g. "max_volume: -10.3 dB"
            parts = line.split(":")
            if len(parts) >= 2:
                val = parts[1].strip().replace(" dB", "").strip()
                try:
                    return float(val)
                except ValueError:
                    continue
    return None


def _parse_mean_volume_from_volumedetect(stderr: str) -> Optional[float]:
    """Extract mean_volume dB from volumedetect output."""
    for line in stderr.splitlines():
        if "mean_volume" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                val = parts[1].strip().replace(" dB", "").strip()
                try:
                    return float(val)
                except ValueError:
                    continue
    return None


def _read_audio_array(audio_path: str) -> tuple[np.ndarray, int]:
    """
    Read audio file into a numpy array using soundfile.
    Returns (samples, sample_rate). Samples shape: (num_samples,) for mono
    or (num_samples, channels) for multi-channel.
    """
    if sf is None:
        raise RuntimeError("soundfile library is required: pip install soundfile")
    data, sr = sf.read(audio_path, dtype="float64")
    return data, sr


def _ensure_mono(samples: np.ndarray) -> np.ndarray:
    """Convert multi-channel to mono by averaging channels."""
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1)


def _dbfs_from_linear(linear: float) -> float:
    """Convert linear amplitude to dBFS."""
    if linear <= 0:
        return -math.inf
    return 20.0 * math.log10(abs(linear))


# ---------------------------------------------------------------------------
# Core checks
# ---------------------------------------------------------------------------

def check_loudness(audio_path: str) -> list[ACXCheck]:
    """
    Measure integrated LUFS (EBU R128) and check against ACX spec.

    Returns a list of ACXCheck results for loudness.
    """
    checks: list[ACXCheck] = []

    if pyloudnorm is None:
        raise RuntimeError("pyloudnorm library is required: pip install pyloudnorm")

    try:
        samples, sr = _read_audio_array(audio_path)
    except Exception as exc:
        checks.append(ACXCheck(
            check_name="loudness_lufs",
            value=0.0,
            threshold=SPEC.TARGET_LUFS,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Failed to read audio: {exc}",
        ))
        return checks

    mono = _ensure_mono(samples)

    # pyloudnorm expects at least ~0.4s of audio; pad if too short
    min_samples = int(sr * 0.4)
    if len(mono) < min_samples:
        mono = np.pad(mono, (0, min_samples - len(mono)))

    meter = pyloudnorm.Meter(sr)
    try:
        lufs = meter.integrated_loudness(mono)
    except Exception as exc:
        checks.append(ACXCheck(
            check_name="loudness_lufs",
            value=0.0,
            threshold=SPEC.TARGET_LUFS,
            passed=False,
            severity=Severity.BLOCK,
            message=f"LUFS measurement failed: {exc}",
        ))
        return checks

    if math.isinf(lufs):
        checks.append(ACXCheck(
            check_name="loudness_lufs",
            value=-math.inf,
            threshold=SPEC.TARGET_LUFS,
            passed=False,
            severity=Severity.BLOCK,
            message="Audio is silent – cannot measure LUFS",
        ))
        return checks

    deviation = abs(lufs - SPEC.TARGET_LUFS)

    if deviation <= SPEC.LUFS_TOLERANCE:
        severity = None
        passed = True
        msg = f"LUFS {lufs:.1f} is within ±{SPEC.LUFS_TOLERANCE} of target {SPEC.TARGET_LUFS}"
    elif deviation <= SPEC.LUFS_WARN:
        severity = Severity.WARNING
        passed = True   # warnings don't fail
        msg = (
            f"LUFS {lufs:.1f} deviates {deviation:.1f} from target "
            f"{SPEC.TARGET_LUFS} (warn threshold ±{SPEC.LUFS_WARN})"
        )
    elif deviation <= SPEC.LUFS_BLOCK:
        severity = Severity.WARNING
        passed = True
        msg = (
            f"LUFS {lufs:.1f} deviates {deviation:.1f} from target "
            f"{SPEC.TARGET_LUFS} (approaching block ±{SPEC.LUFS_BLOCK})"
        )
    else:
        severity = Severity.BLOCK
        passed = False
        msg = (
            f"LUFS {lufs:.1f} deviates {deviation:.1f} from target "
            f"{SPEC.TARGET_LUFS} – exceeds block threshold ±{SPEC.LUFS_BLOCK}"
        )

    checks.append(ACXCheck(
        check_name="loudness_lufs",
        value=lufs,
        threshold=SPEC.TARGET_LUFS,
        passed=passed,
        severity=severity,
        message=msg,
    ))

    return checks


def check_peak(audio_path: str) -> list[ACXCheck]:
    """
    Check peak dBFS level against ACX spec using FFmpeg volumedetect.

    Returns a list of ACXCheck results for peak level.
    """
    checks: list[ACXCheck] = []

    try:
        stderr = _run_ffmpeg_json(audio_path, "volumedetect")
    except RuntimeError as exc:
        checks.append(ACXCheck(
            check_name="peak_dbfs",
            value=0.0,
            threshold=SPEC.PEAK_MAX_DBFS,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Peak measurement failed: {exc}",
        ))
        return checks

    peak_db = _parse_peak_from_volumedetect(stderr)
    if peak_db is None:
        checks.append(ACXCheck(
            check_name="peak_dbfs",
            value=0.0,
            threshold=SPEC.PEAK_MAX_DBFS,
            passed=False,
            severity=Severity.BLOCK,
            message="Could not parse peak level from FFmpeg output",
        ))
        return checks

    # peak_db is max_volume (negative). Closer to 0 = louder.
    # ACX: peak must be ≤ -3 dBFS (i.e. max_volume ≤ -3)
    if peak_db <= SPEC.PEAK_MAX_DBFS:
        severity = None
        passed = True
        msg = f"Peak {peak_db:.1f} dBFS is below {SPEC.PEAK_MAX_DBFS} dBFS limit"
    elif peak_db <= SPEC.PEAK_WARN_DBFS:
        severity = Severity.WARNING
        passed = True
        msg = (
            f"Peak {peak_db:.1f} dBFS exceeds {SPEC.PEAK_MAX_DBFS} dBFS "
            f"(warning threshold {SPEC.PEAK_WARN_DBFS} dBFS)"
        )
    elif peak_db <= SPEC.PEAK_BLOCK_DBFS:
        severity = Severity.WARNING
        passed = True
        msg = (
            f"Peak {peak_db:.1f} dBFS exceeds {SPEC.PEAK_MAX_DBFS} dBFS "
            f"(approaching block {SPEC.PEAK_BLOCK_DBFS} dBFS)"
        )
    else:
        severity = Severity.BLOCK
        passed = False
        msg = (
            f"Peak {peak_db:.1f} dBFS exceeds {SPEC.PEAK_MAX_DBFS} dBFS "
            f"limit – clipping risk (block {SPEC.PEAK_BLOCK_DBFS} dBFS)"
        )

    checks.append(ACXCheck(
        check_name="peak_dbfs",
        value=peak_db,
        threshold=SPEC.PEAK_MAX_DBFS,
        passed=passed,
        severity=severity,
        message=msg,
    ))

    return checks


def check_noise_floor(audio_path: str) -> list[ACXCheck]:
    """
    Estimate noise floor by measuring the quietest 1-second segment
    using FFmpeg's astats filter on a silencedetect basis, or by
    computing RMS of the quietest portions of the audio.

    Returns a list of ACXCheck results for noise floor.
    """
    checks: list[ACXCheck] = []

    try:
        samples, sr = _read_audio_array(audio_path)
    except Exception as exc:
        checks.append(ACXCheck(
            check_name="noise_floor_dbfs",
            value=0.0,
            threshold=SPEC.NOISE_FLOOR_DBFS,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Failed to read audio for noise floor: {exc}",
        ))
        return checks

    mono = _ensure_mono(samples)

    if len(mono) == 0:
        checks.append(ACXCheck(
            check_name="noise_floor_dbfs",
            value=-math.inf,
            threshold=SPEC.NOISE_FLOOR_DBFS,
            passed=True,
            severity=None,
            message="Audio is silent – noise floor is effectively -inf dBFS",
        ))
        return checks

    # Compute RMS over 1-second windows and take the quietest
    window_size = sr  # 1 second
    if len(mono) < window_size:
        # Short file: measure entire thing
        rms_val = np.sqrt(np.mean(mono ** 2))
        noise_db = _dbfs_from_linear(rms_val) if rms_val > 0 else -math.inf
    else:
        num_windows = len(mono) // window_size
        rms_values = []
        for i in range(num_windows):
            chunk = mono[i * window_size : (i + 1) * window_size]
            rms_val = np.sqrt(np.mean(chunk ** 2))
            if rms_val > 0:
                rms_values.append(rms_val)
        if not rms_values:
            noise_db = -math.inf
        else:
            # Use the quietest 10th-percentile window as noise floor estimate
            rms_values.sort()
            idx = max(0, int(len(rms_values) * 0.1) - 1)
            noise_db = _dbfs_from_linear(rms_values[idx])

    if noise_db <= SPEC.NOISE_FLOOR_DBFS:
        severity = None
        passed = True
        msg = f"Noise floor {noise_db:.1f} dBFS is below {SPEC.NOISE_FLOOR_DBFS} dBFS limit"
    elif noise_db <= SPEC.NOISE_WARN_DBFS:
        severity = Severity.WARNING
        passed = True
        msg = (
            f"Noise floor {noise_db:.1f} dBFS exceeds {SPEC.NOISE_FLOOR_DBFS} dBFS "
            f"(warning threshold {SPEC.NOISE_WARN_DBFS} dBFS)"
        )
    elif noise_db <= SPEC.NOISE_BLOCK_DBFS:
        severity = Severity.WARNING
        passed = True
        msg = (
            f"Noise floor {noise_db:.1f} dBFS exceeds {SPEC.NOISE_FLOOR_DBFS} dBFS "
            f"(approaching block {SPEC.NOISE_BLOCK_DBFS} dBFS)"
        )
    else:
        severity = Severity.BLOCK
        passed = False
        msg = (
            f"Noise floor {noise_db:.1f} dBFS exceeds {SPEC.NOISE_FLOOR_DBFS} dBFS "
            f"limit – too noisy (block {SPEC.NOISE_BLOCK_DBFS} dBFS)"
        )

    checks.append(ACXCheck(
        check_name="noise_floor_dbfs",
        value=noise_db,
        threshold=SPEC.NOISE_FLOOR_DBFS,
        passed=passed,
        severity=severity,
        message=msg,
    ))

    return checks


def check_room_tone(audio_path: str) -> list[ACXCheck]:
    """
    Check that the head and tail of the audio contain room tone
    (low-level ambient sound in the range 0.5–1.0 seconds).

    Uses FFmpeg silencedetect to find silence regions at the
    beginning and end of the file.
    """
    checks: list[ACXCheck] = []

    # First get total duration
    try:
        stderr = _run_ffmpeg_json(audio_path, "anull")
    except RuntimeError as exc:
        checks.append(ACXCheck(
            check_name="room_tone",
            value=0.0,
            threshold=SPEC.ROOM_TONE_MIN_S,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Could not determine audio duration: {exc}",
        ))
        return checks

    # Parse duration from stderr
    duration = None
    for line in stderr.splitlines():
        if "Duration:" in line:
            # e.g. "  Duration: 00:05:23.45, start: 0.000000, bitrate: 1411 kb/s"
            try:
                dur_str = line.split("Duration:")[1].split(",")[0].strip()
                parts = dur_str.split(":")
                h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
                duration = h * 3600 + m * 60 + s
            except (IndexError, ValueError):
                pass
            break

    if duration is None or duration < SPEC.ROOM_TONE_MIN_S:
        checks.append(ACXCheck(
            check_name="room_tone",
            value=duration or 0.0,
            threshold=SPEC.ROOM_TONE_MIN_S,
            passed=False,
            severity=Severity.BLOCK,
            message=(
                f"Audio too short ({duration:.2f}s) for room tone check – "
                f"minimum {SPEC.ROOM_TONE_MIN_S}s required"
            ),
        ))
        return checks

    # Use silencedetect to find silence at head and tail
    silence_thresh = -50.0  # dBFS – what counts as "room tone / quiet"
    min_silence_dur = 100   # ms

    try:
        stderr_silence = _run_ffmpeg_json(
            audio_path,
            f"silencedetect=noise={silence_thresh}dB:d={min_silence_dur / 1000:.2f}"
        )
    except RuntimeError as exc:
        checks.append(ACXCheck(
            check_name="room_tone",
            value=0.0,
            threshold=SPEC.ROOM_TONE_MIN_S,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Silence detection failed: {exc}",
        ))
        return checks

    # Parse silence_start / silence_end from stderr
    silence_periods: list[tuple[float, float]] = []
    current_start: Optional[float] = None

    for line in stderr_silence.splitlines():
        if "silence_start:" in line:
            try:
                val = line.split("silence_start:")[1].strip().split()[0]
                current_start = float(val)
            except (IndexError, ValueError):
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("silence_end:")[1].strip().split()
                end_val = float(parts[0])
                silence_periods.append((current_start, end_val))
                current_start = None
            except (IndexError, ValueError):
                current_start = None

    # If a silence region starts at 0 and hasn't ended, it extends to end
    if current_start is not None:
        silence_periods.append((current_start, duration))

    # Check head room tone: silence starting at or near 0
    head_tone_ok = False
    head_tone_duration = 0.0
    for start, end in silence_periods:
        if start <= 0.1:  # within 100ms of start
            head_tone_duration = end - start
            if SPEC.ROOM_TONE_MIN_S <= head_tone_duration <= SPEC.ROOM_TONE_MAX_S:
                head_tone_ok = True
            break

    # Check tail room tone: silence ending at or near duration
    tail_tone_ok = False
    tail_tone_duration = 0.0
    for start, end in reversed(silence_periods):
        if end >= duration - 0.1:  # within 100ms of end
            tail_tone_duration = end - start
            if SPEC.ROOM_TONE_MIN_S <= tail_tone_duration <= SPEC.ROOM_TONE_MAX_S:
                tail_tone_ok = True
            break

    if head_tone_ok and tail_tone_ok:
        checks.append(ACXCheck(
            check_name="room_tone",
            value=min(head_tone_duration, tail_tone_duration),
            threshold=SPEC.ROOM_TONE_MIN_S,
            passed=True,
            severity=None,
            message=(
                f"Head room tone {head_tone_duration:.2f}s, "
                f"tail room tone {tail_tone_duration:.2f}s – both within "
                f"{SPEC.ROOM_TONE_MIN_S}–{SPEC.ROOM_TONE_MAX_S}s range"
            ),
        ))
    else:
        parts = []
        if not head_tone_ok:
            parts.append(
                f"head tone {head_tone_duration:.2f}s "
                f"(need {SPEC.ROOM_TONE_MIN_S}–{SPEC.ROOM_TONE_MAX_S}s)"
            )
        if not tail_tone_ok:
            parts.append(
                f"tail tone {tail_tone_duration:.2f}s "
                f"(need {SPEC.ROOM_TONE_MIN_S}–{SPEC.ROOM_TONE_MAX_S}s)"
            )
        checks.append(ACXCheck(
            check_name="room_tone",
            value=min(head_tone_duration, tail_tone_duration),
            threshold=SPEC.ROOM_TONE_MIN_S,
            passed=False,
            severity=Severity.BLOCK,
            message=f"Room tone issue: {'; '.join(parts)}",
        ))

    return checks


# ---------------------------------------------------------------------------
# Aggregated checks
# ---------------------------------------------------------------------------

def check_chapter(audio_path: str) -> dict:
    """
    Run all ACX compliance checks on a single chapter audio file.

    Returns:
        {
            "passed": bool,
            "policy": str,           # "acx_v2024"
            "checks": [dict, ...],   # serialized ACXCheck list
            "summary": str,
        }
    """
    all_checks: list[ACXCheck] = []
    errors: list[str] = []

    for check_fn in (check_loudness, check_peak, check_noise_floor, check_room_tone):
        try:
            results = check_fn(audio_path)
            all_checks.extend(results)
        except Exception as exc:
            err_msg = f"{check_fn.__name__} failed: {exc}"
            logger.error(err_msg, exc_info=True)
            errors.append(err_msg)
            all_checks.append(ACXCheck(
                check_name=check_fn.__name__,
                value=0.0,
                threshold=0.0,
                passed=False,
                severity=Severity.BLOCK,
                message=err_msg,
            ))

    passed = all(c.passed for c in all_checks)
    block_count = sum(1 for c in all_checks if c.severity == Severity.BLOCK and not c.passed)
    warn_count = sum(1 for c in all_checks if c.severity == Severity.WARNING)

    if passed and warn_count == 0:
        summary = "All ACX checks passed."
    elif passed and warn_count > 0:
        summary = f"ACX checks passed with {warn_count} warning(s)."
    else:
        failed_names = [c.check_name for c in all_checks if not c.passed]
        summary = (
            f"ACX checks FAILED – {block_count} blocking issue(s). "
            f"Failed: {', '.join(failed_names)}"
        )

    if errors:
        summary += f" ({len(errors)} check(s) encountered errors)"

    return {
        "passed": passed,
        "policy": "acx_v2024",
        "checks": [c.to_dict() for c in all_checks],
        "summary": summary,
    }


def check_full_book(chapter_paths: list[str]) -> dict:
    """
    Check all chapters of a book for ACX compliance.

    Returns:
        {
            "passed": bool,             # True only if ALL chapters pass
            "policy": str,
            "total_chapters": int,
            "passed_chapters": int,
            "failed_chapters": int,
            "chapters": [
                {
                    "path": str,
                    "passed": bool,
                    "checks": [dict, ...],
                    "summary": str,
                },
                ...
            ],
            "summary": str,
        }
    """
    chapter_results: list[dict] = []
    passed_count = 0
    failed_count = 0

    for idx, path in enumerate(chapter_paths, start=1):
        logger.info("Checking chapter %d/%d: %s", idx, len(chapter_paths), path)
        try:
            result = check_chapter(path)
        except Exception as exc:
            logger.error("Chapter %d check failed: %s", idx, exc, exc_info=True)
            result = {
                "passed": False,
                "policy": "acx_v2024",
                "checks": [],
                "summary": f"Error checking chapter: {exc}",
            }

        chapter_entry = {
            "path": path,
            "passed": result["passed"],
            "checks": result["checks"],
            "summary": result["summary"],
        }
        chapter_results.append(chapter_entry)

        if result["passed"]:
            passed_count += 1
        else:
            failed_count += 1

    overall_passed = failed_count == 0

    if overall_passed:
        summary = f"All {len(chapter_paths)} chapter(s) passed ACX compliance."
    else:
        summary = (
            f"{failed_count} of {len(chapter_paths)} chapter(s) failed "
            f"ACX compliance. {passed_count} passed."
        )

    return {
        "passed": overall_passed,
        "policy": "acx_v2024",
        "total_chapters": len(chapter_paths),
        "passed_chapters": passed_count,
        "failed_chapters": failed_count,
        "chapters": chapter_results,
        "summary": summary,
    }
