"""Media validation between synthesis and QC (P1.1).

A 200 from a provider is not proof of usable audio. Every artifact — fresh
synthesis, cache hit, or assembled chapter — passes through validate_media()
before it can advance chapter state, be billed, or reach assembly.

Each rule has a distinct machine-readable `reason` so tests (and operators)
can assert an artifact was rejected by the rule that targets its failure
shape, not incidentally caught by an earlier check:

    missing               file does not exist
    empty                 zero bytes
    decode_failed         no identifiable audio stream / undecodable
    wrong_format          decodable audio, but not MP3 container+codec
    no_duration           decodes to zero duration
    bad_stream_params     channels/sample-rate outside sane bounds
    truncated             header claims materially more audio than decodes
    silent                decodable but pure silence
    implausible_duration  duration wildly off for the character count

The truncation rule leans on a deliberate property of MP3+Xing: ffprobe
reports the header-claimed duration while an actual decode yields only what
survives, so a stream cut mid-frame shows header ≫ decoded. This is why the
fake provider renders to a seekable file (Xing finalized) rather than a pipe.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from utils.audio_utils import CHARS_PER_SECOND

# Version stamp for the whole validation+QC profile. Recorded on every
# chapter row so books built under an older policy stay interpretable when
# thresholds change.
QC_POLICY_VERSION = "p1.1-2026.08.12"

# A file is "silent" (hard reject) below this whole-file level. QC's advisory
# loudness warning sits at -45 dBFS (utils.audio_utils._LOUDNESS_WARN_DBFS);
# the gap between -45 and -60 is "suspiciously quiet" — QC's business, not a
# validation reject.
_SILENT_DBFS = -60.0

# Header duration may exceed decoded duration by this factor before we call
# the file truncated (VBR estimates wobble a little; a mid-frame cut doesn't).
_TRUNCATION_RATIO = 1.10
_TRUNCATION_SLACK_S = 0.5

# Plausibility band around expected duration (chars / CHARS_PER_SECOND).
_PLAUSIBLE_RATIO = 3.0
_PLAUSIBLE_SLACK_S = 5.0


@dataclass
class MediaValidationResult:
    ok: bool
    reason: Optional[str]
    detail: str
    header_duration_s: Optional[float] = None
    decoded_duration_s: Optional[float] = None
    dbfs: Optional[float] = None


class MediaValidationError(RuntimeError):
    """Raised by the pipeline when an artifact is rejected.

    Subclasses RuntimeError so existing job-failure handling (record attempt,
    backoff, requeue) applies unchanged.
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason


def _ffprobe(path: str) -> Optional[dict]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, check=True, timeout=60,
        )
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return None


def validate_media(
    path: str,
    expected_chars: Optional[int] = None,
    expected_extra_s: float = 0.0,
) -> MediaValidationResult:
    """Validate one audio artifact. Never raises; returns a result object.

    expected_chars: character count of the text this audio was synthesized
    from — drives the duration-plausibility rule (skipped when None).
    expected_extra_s: additional legitimate duration beyond the text's own
    (e.g. inter-chunk silence gaps in an assembled chapter).
    """
    if not os.path.isfile(path):
        return MediaValidationResult(False, "missing", f"file not found: {path}")
    size = os.path.getsize(path)
    if size == 0:
        return MediaValidationResult(False, "empty", f"zero-byte file: {path}")

    probe = _ffprobe(path)
    audio_streams = [
        s for s in (probe or {}).get("streams", [])
        if s.get("codec_type") == "audio"
    ]
    if probe is None or not audio_streams:
        return MediaValidationResult(
            False, "decode_failed", f"no identifiable audio stream in {size} bytes"
        )

    fmt_name = probe.get("format", {}).get("format_name", "")
    codec = audio_streams[0].get("codec_name", "")
    if "mp3" not in fmt_name or codec != "mp3":
        return MediaValidationResult(
            False, "wrong_format",
            f"expected mp3 container+codec, got format={fmt_name!r} codec={codec!r}",
        )

    # Actual decode: what really survives in the stream (import here so the
    # module stays importable for its constants without pydub present).
    from pydub import AudioSegment
    try:
        seg = AudioSegment.from_file(path, format="mp3")
    except Exception as exc:  # noqa: BLE001 — pydub raises various types
        return MediaValidationResult(
            False, "decode_failed", f"mp3 decode failed: {exc}"
        )

    decoded_s = len(seg) / 1000.0
    header_s: Optional[float] = None
    raw_header = probe.get("format", {}).get("duration")
    if raw_header is not None:
        try:
            header_s = float(raw_header)
        except (TypeError, ValueError):
            header_s = None

    if decoded_s <= 0:
        return MediaValidationResult(
            False, "no_duration", "decodes to zero duration",
            header_duration_s=header_s, decoded_duration_s=decoded_s,
        )

    channels = audio_streams[0].get("channels")
    sample_rate = int(audio_streams[0].get("sample_rate") or 0)
    if channels not in (1, 2) or sample_rate < 8000:
        return MediaValidationResult(
            False, "bad_stream_params",
            f"channels={channels} sample_rate={sample_rate}",
            header_duration_s=header_s, decoded_duration_s=decoded_s,
        )

    if header_s is not None and header_s > decoded_s * _TRUNCATION_RATIO + _TRUNCATION_SLACK_S:
        return MediaValidationResult(
            False, "truncated",
            f"header claims {header_s:.2f}s but only {decoded_s:.2f}s decodes",
            header_duration_s=header_s, decoded_duration_s=decoded_s,
        )

    dbfs = seg.dBFS  # -inf for digital silence
    if dbfs < _SILENT_DBFS:
        return MediaValidationResult(
            False, "silent", f"whole-file level {dbfs} dBFS",
            header_duration_s=header_s, decoded_duration_s=decoded_s, dbfs=dbfs,
        )

    if expected_chars is not None and expected_chars > 0:
        expected_s = expected_chars / CHARS_PER_SECOND
        lo = max(0.0, expected_s / _PLAUSIBLE_RATIO - _PLAUSIBLE_SLACK_S)
        hi = expected_s * _PLAUSIBLE_RATIO + expected_extra_s + _PLAUSIBLE_SLACK_S
        if not (lo <= decoded_s <= hi):
            return MediaValidationResult(
                False, "implausible_duration",
                f"{decoded_s:.2f}s decoded for {expected_chars} chars "
                f"(expected ≈{expected_s:.2f}s, accepted [{lo:.2f}, {hi:.2f}])",
                header_duration_s=header_s, decoded_duration_s=decoded_s, dbfs=dbfs,
            )

    return MediaValidationResult(
        True, None, "ok",
        header_duration_s=header_s, decoded_duration_s=decoded_s, dbfs=dbfs,
    )
