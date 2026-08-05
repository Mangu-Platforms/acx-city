"""Pipeline configuration — 30+ registered constants with validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


class ConfigValidationError(Exception):
    """Raised when a PipelineConfig fails validation.

    validate() returns the violation list; callers that need hard failure
    wrap it in this exception.
    """


@dataclass
class ConfigField:
    """Metadata for a single configuration constant."""
    name: str
    type: type
    default: Any = None
    required: bool = False
    min_val: float | None = None
    max_val: float | None = None
    description: str = ""


# Registry of all configuration constants
CONFIG_REGISTRY: list[ConfigField] = [
    ConfigField("manuscript_path", str, required=True, description="Path to input manuscript"),
    ConfigField("run_root", str, default=None, description="Root directory for run artifacts"),
    ConfigField("auto_mode", bool, default=True, description="Enable auto-waiving of checkpoints"),
    ConfigField("api_url", str, default="http://localhost:5000", description="ACX City API base URL"),
    ConfigField("api_key", str, default=None, description="Bearer key for API authentication"),
    ConfigField("max_chapters", int, default=500, min_val=1, max_val=5000, description="Maximum chapters per book"),
    ConfigField("max_words_per_chapter", int, default=50000, min_val=100, max_val=200000, description="Max words per chapter"),
    ConfigField("target_loudness_lufs", float, default=-23.0, min_val=-30.0, max_val=-10.0, description="Target loudness in LUFS"),
    ConfigField("target_peak_dbfs", float, default=-3.0, min_val=-10.0, max_val=0.0, description="Target peak level in dBFS"),
    ConfigField("noise_floor_dbfs", float, default=-60.0, min_val=-80.0, max_val=-30.0, description="Maximum noise floor"),
    ConfigField("silence_threshold_db", float, default=-50.0, min_val=-70.0, max_val=-20.0, description="Silence detection threshold"),
    ConfigField("silence_min_duration", float, default=0.5, min_val=0.1, max_val=5.0, description="Minimum silence duration (seconds)"),
    ConfigField("padding_before_s", float, default=0.5, min_val=0.0, max_val=3.0, description="Padding before each chapter"),
    ConfigField("padding_after_s", float, default=1.0, min_val=0.0, max_val=5.0, description="Padding after each chapter"),
    ConfigField("ffmpeg_path", str, default="ffmpeg", description="Path to ffmpeg binary"),
    ConfigField("ffprobe_path", str, default="ffprobe", description="Path to ffprobe binary"),
    ConfigField("tts_engine", str, default="edge-tts", description="TTS engine to use"),
    ConfigField("tts_voice_id", str, default="en-US-AriaNeural", description="Default TTS voice"),
    ConfigField("tts_rate", str, default="+0%", description="TTS speaking rate adjustment"),
    ConfigField("tts_volume", str, default="+0%", description="TTS volume adjustment"),
    ConfigField("output_format", str, default="m4b", description="Output audio format"),
    ConfigField("output_bitrate", str, default="128k", description="Output audio bitrate"),
    ConfigField("sample_rate", int, default=44100, min_val=22050, max_val=96000, description="Audio sample rate"),
    ConfigField("channels", int, default=1, min_val=1, max_val=2, description="Audio channels"),
    ConfigField("cover_min_width", int, default=2400, min_val=1400, max_val=5000, description="Minimum cover art width"),
    ConfigField("cover_min_height", int, default=2400, min_val=1400, max_val=5000, description="Minimum cover art height"),
    ConfigField("cover_format", str, default="jpeg", description="Cover art format"),
    ConfigField("checkpoint_timeout_s", int, default=3600, min_val=60, max_val=86400, description="Checkpoint wait timeout"),
    ConfigField("synthesis_cache_enabled", bool, default=True, description="Enable content-addressed synthesis cache"),
    ConfigField("max_concurrent_synthesis", int, default=4, min_val=1, max_val=16, description="Max concurrent synthesis workers"),
    ConfigField("log_level", str, default="INFO", description="Logging level"),
    ConfigField("edge_tts_version", str, default="7.0.0", description="Pinned edge-tts version"),
    ConfigField("mcp_write_enabled", bool, default=False, description="Enable MCP write tools"),
]


@dataclass
class PipelineConfig:
    """The validated pipeline configuration."""
    # None = template not yet bound to a manuscript (valid); an explicit ""
    # is a provided-but-missing value and fails validation.
    manuscript_path: str | None = None
    run_root: str | None = None
    auto_mode: bool = True
    api_url: str = "http://localhost:5000"
    api_key: str | None = None
    max_chapters: int = 500
    max_words_per_chapter: int = 50000
    target_loudness_lufs: float = -23.0
    target_peak_dbfs: float = -3.0
    noise_floor_dbfs: float = -60.0
    silence_threshold_db: float = -50.0
    silence_min_duration: float = 0.5
    padding_before_s: float = 0.5
    padding_after_s: float = 1.0
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    tts_engine: str = "edge-tts"
    tts_voice_id: str = "en-US-AriaNeural"
    tts_rate: str = "+0%"
    tts_volume: str = "+0%"
    output_format: str = "m4b"
    output_bitrate: str = "128k"
    sample_rate: int = 44100
    channels: int = 1
    cover_min_width: int = 2400
    cover_min_height: int = 2400
    cover_format: str = "jpeg"
    checkpoint_timeout_s: int = 3600
    synthesis_cache_enabled: bool = True
    max_concurrent_synthesis: int = 4
    log_level: str = "INFO"
    edge_tts_version: str = "7.0.0"
    mcp_write_enabled: bool = False

    def validate(self) -> list[str]:
        """Validate all fields. Returns list of violation descriptions."""
        errors = []
        for field_meta in CONFIG_REGISTRY:
            value = getattr(self, field_meta.name, None)

            if field_meta.required and value == "":
                errors.append(f"{field_meta.name}: required but not provided")
                continue

            if value is None:
                continue

            if not isinstance(value, field_meta.type):
                errors.append(
                    f"{field_meta.name}: expected {field_meta.type.__name__}, "
                    f"got {type(value).__name__}"
                )
                continue

            if field_meta.min_val is not None and value < field_meta.min_val:
                errors.append(
                    f"{field_meta.name}: {value} < minimum {field_meta.min_val}"
                )
            if field_meta.max_val is not None and value > field_meta.max_val:
                errors.append(
                    f"{field_meta.name}: {value} > maximum {field_meta.max_val}"
                )

        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Load config from environment variables (PIPELINE_ prefix)."""
        import os
        kwargs = {}
        for field_meta in CONFIG_REGISTRY:
            env_key = f"PIPELINE_{field_meta.name.upper()}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                if field_meta.type is bool:
                    kwargs[field_meta.name] = env_val.lower() in ("true", "1", "yes")
                elif field_meta.type is int:
                    kwargs[field_meta.name] = int(env_val)
                elif field_meta.type is float:
                    kwargs[field_meta.name] = float(env_val)
                else:
                    kwargs[field_meta.name] = env_val
        return cls(**kwargs)
