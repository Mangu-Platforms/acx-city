"""P1.0: FakeSpeechProvider emits real, decodable, deterministic audio.

Each failure mode must produce the specifically-shaped bad artifact it
advertises, because P1.1's media-validation gate asserts that each mode is
rejected by the specific rule it targets — not incidentally caught earlier.
"""
import io
import json
import shutil
import subprocess

import pytest
from pydub import AudioSegment

from services.providers.fake_provider import FakeSpeechProvider
from utils.audio_utils import CHARS_PER_SECOND

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe required",
)

TEXT = "It was a bright cold day in April, and the clocks were striking thirteen. " * 4


@pytest.fixture()
def fake():
    return FakeSpeechProvider()


def _decode(data: bytes) -> AudioSegment:
    return AudioSegment.from_file(io.BytesIO(data), format="mp3")


def _probe(tmp_path, data: bytes, name="a.bin") -> dict:
    p = tmp_path / name
    p.write_bytes(data)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(p)],
        capture_output=True, check=True, timeout=60,
    )
    return json.loads(out.stdout)


def test_success_is_decodable_nonsilent_and_plausible(fake):
    data = fake.synthesize(TEXT, "fake-a")
    seg = _decode(data)
    assert seg.dBFS > -45, "success audio must not be silent"
    expected_s = len(TEXT) / CHARS_PER_SECOND
    assert abs(len(seg) / 1000.0 - expected_s) < max(1.0, expected_s * 0.1), (
        f"duration {len(seg)/1000.0:.2f}s should track ~{expected_s:.2f}s"
    )


def test_success_is_deterministic(fake):
    a = fake.synthesize(TEXT, "fake-a")
    b = FakeSpeechProvider().synthesize(TEXT, "fake-a")
    assert a == b, "identical input must yield byte-identical output"
    assert a != fake.synthesize(TEXT, "fake-b"), "different voice, different audio"
    assert a != fake.synthesize(TEXT + " More.", "fake-a"), "different text, different audio"


def test_options_change_the_audio(fake):
    plain = fake.synthesize(TEXT, "fake-a")
    styled = fake.synthesize_with_options(TEXT, "fake-a", rate="+10%", style="cheerful")
    assert plain != styled, "directed render must differ from plain render"


def test_invalid_audio_has_no_valid_header(fake, tmp_path):
    data = fake.synthesize(f"[fake:invalid_audio]{TEXT}", "fake-a")
    assert len(data) > 1000, "invalid artifact must have plausible byte length"
    with pytest.raises(Exception):
        _decode(data)
    p = tmp_path / "bad.bin"
    p.write_bytes(data)
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(p)],
        capture_output=True, timeout=60,
    )
    # ffprobe may guess a non-audio demuxer for garbage; what matters is that
    # it never identifies decodable audio and never calls it mp3.
    if r.returncode == 0:
        info = json.loads(r.stdout)
        assert "mp3" not in info.get("format", {}).get("format_name", "")
        audio_streams = [s for s in info.get("streams", [])
                         if s.get("codec_type") == "audio"]
        assert not audio_streams, f"garbage identified as audio: {audio_streams}"


def test_truncated_audio_header_claims_more_than_decodes(fake, tmp_path):
    marker_text = f"[fake:truncated_audio]{TEXT}"
    data = fake.synthesize(marker_text, "fake-a")
    header_s = float(_probe(tmp_path, data, "trunc.mp3")["format"]["duration"])
    decoded_s = len(_decode(data)) / 1000.0
    assert header_s > decoded_s * 1.5, (
        f"truncation signature missing: header={header_s:.2f}s decoded={decoded_s:.2f}s"
    )


def test_silent_audio_is_decodable_pure_silence(fake):
    data = fake.synthesize(f"[fake:silent_audio]{TEXT}", "fake-a")
    seg = _decode(data)
    assert len(seg) > 1000, "silent artifact must still have real duration"
    assert seg.dBFS < -60, f"expected digital silence, got {seg.dBFS} dBFS"


def test_wrong_duration_is_valid_but_implausible(fake):
    data = fake.synthesize(f"[fake:wrong_duration]{TEXT}", "fake-a")
    seg = _decode(data)
    expected_s = len(TEXT) / CHARS_PER_SECOND
    actual_s = len(seg) / 1000.0
    ratio = actual_s / expected_s
    assert ratio > 4 or ratio < 0.25, (
        f"duration must be wildly off: {actual_s:.1f}s vs expected {expected_s:.1f}s"
    )


def test_wrong_format_is_valid_audio_wrong_container(fake, tmp_path):
    data = fake.synthesize(f"[fake:wrong_format]{TEXT}", "fake-a")
    fmt = _probe(tmp_path, data, "wf.bin")["format"]["format_name"]
    assert "wav" in fmt and "mp3" not in fmt


def test_marker_is_stripped_from_duration_law(fake):
    plain = fake.synthesize(TEXT, "fake-a")
    marked = fake.synthesize(f"[fake:success]{TEXT}", "fake-a")
    assert plain == marked, "marker must not affect derived audio"


def test_temporary_failure_succeeds_on_retry(fake):
    text = f"[fake:temporary_failure]{TEXT}"
    with pytest.raises(RuntimeError, match="temporary failure"):
        fake.synthesize(text, "fake-a")
    data = fake.synthesize(text, "fake-a")
    assert _decode(data).dBFS > -45


def test_permanent_failure_always_raises(fake):
    text = f"[fake:permanent_failure]{TEXT}"
    for _ in range(3):
        with pytest.raises(RuntimeError, match="permanent failure"):
            fake.synthesize(text, "fake-a")


def test_fail_after_n_calls(fake):
    fake.fail_after_n_calls = 2
    fake.synthesize(TEXT, "fake-a")
    fake.synthesize(TEXT, "fake-b")
    with pytest.raises(RuntimeError, match="failing after 2"):
        fake.synthesize(TEXT, "fake-a")
