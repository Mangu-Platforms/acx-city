"""
M4B Audiobook Assembly Service

Assembles chapter MP3s into M4B audiobooks with chapter markers,
ID3 metadata, and multi-format export support.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AssemblyError(Exception):
    """Raised when M4B assembly operations fail."""


def _run_ffmpeg(args: list[str], description: str = "FFmpeg operation") -> subprocess.CompletedProcess:
    """Run an FFmpeg command with error handling and logging."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    logger.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,
        )
        if result.returncode != 0:
            logger.error("%s failed (exit %d): %s", description, result.returncode, result.stderr)
            raise AssemblyError(f"{description} failed: {result.stderr.strip()}")
        return result
    except FileNotFoundError:
        raise AssemblyError("ffmpeg not found. Please install FFmpeg.")
    except subprocess.TimeoutExpired:
        raise AssemblyError(f"{description} timed out after 3600s")


def _probe_duration(path: str) -> float:
    """Get duration in seconds of an audio file via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        raise AssemblyError(f"Cannot probe duration of {path}: {exc}")


def generate_chapter_atoms(chapter_paths: list[str]) -> list[dict]:
    """
    Calculate start_time and end_time for each chapter from MP3 durations.

    Returns a list of dicts with keys: index, title (placeholder), start_time, end_time.
    Times are in milliseconds (int).
    """
    if not chapter_paths:
        return []

    chapters: list[dict] = []
    current_ms = 0

    for idx, path in enumerate(chapter_paths):
        duration_sec = _probe_duration(path)
        duration_ms = int(round(duration_sec * 1000))
        chapters.append({
            "index": idx,
            "start_time": current_ms,
            "end_time": current_ms + duration_ms,
        })
        current_ms += duration_ms

    return chapters


def embed_chapter_markers(
    input_path: str,
    chapters: list[dict],
    output_path: str,
) -> str:
    """
    Use FFmpeg to embed chapter markers into an M4B/M4A file.

    Each chapter dict must have: start_time (ms), end_time (ms), and optionally 'title'.
    """
    if not chapters:
        raise AssemblyError("No chapters provided for marker embedding")

    # Build FFmpeg metadata file with chapter atoms
    metadata_lines = [";FFMETADATA1"]
    for ch in chapters:
        start_us = ch["start_time"] * 1000  # ms → µs
        end_us = ch["end_time"] * 1000
        title = ch.get("title", f"Chapter {ch.get('index', 0) + 1}")
        metadata_lines.append("[CHAPTER]")
        metadata_lines.append("TIMEBASE=1/1000000")
        metadata_lines.append(f"START={start_us}")
        metadata_lines.append(f"END={end_us}")
        metadata_lines.append(f"title={title}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(metadata_lines) + "\n")
        meta_path = f.name

    try:
        _run_ffmpeg(
            ["-i", input_path, "-i", meta_path, "-map_metadata", "1", "-codec", "copy", output_path],
            description="Embed chapter markers",
        )
    finally:
        os.unlink(meta_path)

    logger.info("Embedded %d chapter markers → %s", len(chapters), output_path)
    return output_path


def embed_metadata(
    input_path: str,
    metadata: dict,
    output_path: str,
    cover_path: Optional[str] = None,
) -> None:
    """
    Embed title, author, narrator, year, and cover art via FFmpeg.

    metadata keys: title, artist/author, album_artist/narrator, year, genre.
    cover_path: optional path to a cover image (JPEG/PNG).
    """
    args: list[str] = ["-i", input_path]

    # Cover art input
    has_cover = cover_path and os.path.isfile(cover_path)
    if has_cover:
        args = ["-i", cover_path, "-i", input_path]

    # Map streams
    if has_cover:
        args += ["-map", "1:a", "-map", "0:v"]
    else:
        args += ["-map", "0"]

    # Metadata tags
    tag_map = {
        "title": "title",
        "artist": "artist",
        "author": "artist",
        "album_artist": "album_artist",
        "narrator": "album_artist",
        "album": "album",
        "year": "date",
        "genre": "genre",
        "comment": "comment",
        "description": "description",
    }

    for meta_key, ffmpeg_key in tag_map.items():
        value = metadata.get(meta_key)
        if value is not None:
            args += ["-metadata", f"{ffmpeg_key}={value}"]

    # Default narrator if not set
    if "narrator" not in metadata and "album_artist" not in metadata:
        args += ["-metadata", "album_artist=ACX City Synthetic"]

    # Codec copy when possible; for cover embedding we may need re-mux
    args += ["-c", "copy"]
    if has_cover:
        args += ["-c:v", "mjpeg", "-disposition:v", "attached_pic"]

    args.append(output_path)

    _run_ffmpeg(args, description="Embed metadata")
    logger.info("Embedded metadata → %s", output_path)


def assemble_m4b(
    chapter_mp3_paths: list[str],
    chapter_titles: list[str],
    metadata: dict,
    output_path: str,
) -> str:
    """
    Assemble an M4B audiobook from chapter MP3 files.

    Steps:
      1. Concatenate chapter MP3s into a single AAC stream.
      2. Embed chapter atoms with start/end times and titles.
      3. Embed ID3/M4B metadata (title, author, narrator, year, cover art).

    Args:
        chapter_mp3_paths: Ordered list of MP3 file paths.
        chapter_titles: Chapter titles (same length as chapter_mp3_paths).
        metadata: Dict with keys: title, author, artist, narrator, year,
                  genre, album, cover_path, comment, description.
        output_path: Destination .m4b file path.

    Returns:
        The output_path on success.
    """
    if not chapter_mp3_paths:
        raise AssemblyError("No chapter MP3 files provided")
    if len(chapter_mp3_paths) != len(chapter_titles):
        raise AssemblyError(
            f"Chapter count mismatch: {len(chapter_mp3_paths)} paths vs {len(chapter_titles)} titles"
        )

    output_path = str(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # --- Step 1: Generate chapter time atoms ---
    logger.info("Probing %d chapter durations…", len(chapter_mp3_paths))
    chapters = generate_chapter_atoms(chapter_mp3_paths)
    for ch, title in zip(chapters, chapter_titles):
        ch["title"] = title

    # --- Step 2: Concatenate MP3s and transcode to AAC ---
    # Build FFmpeg concat file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for path in chapter_mp3_paths:
            escaped = path.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        concat_list_path = f.name

    # Temporary AAC file before metadata/chapters
    tmp_aac = tempfile.NamedTemporaryFile(suffix=".m4b", delete=False).name

    try:
        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0", "-i", concat_list_path,
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-vn",  # strip any video
                tmp_aac,
            ],
            description="Concatenate and transcode to AAC",
        )

        # --- Step 3: Embed chapter markers ---
        tmp_chapters = tempfile.NamedTemporaryFile(suffix=".m4b", delete=False).name
        try:
            embed_chapter_markers(tmp_aac, chapters, tmp_chapters)

            # --- Step 4: Embed metadata + cover art ---
            cover_path = metadata.get("cover_path")
            embed_metadata(tmp_chapters, metadata, output_path, cover_path=cover_path)
        finally:
            _safe_unlink(tmp_chapters)
    finally:
        _safe_unlink(concat_list_path)
        _safe_unlink(tmp_aac)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(
        "Assembled M4B: %d chapters, %.1f MB → %s",
        len(chapter_mp3_paths), size_mb, output_path,
    )
    return output_path


def export_formats(
    audio_path: str,
    formats: list[str],
    output_dir: str,
) -> dict[str, str]:
    """
    Export an audio file to multiple formats.

    Supported formats and settings:
      - mp3:  128 kbps CBR, 44.1 kHz
      - m4b:  AAC codec, default bitrate
      - wav:  24-bit PCM, 48 kHz

    Args:
        audio_path: Source audio file.
        formats: List of format strings ("mp3", "m4b", "wav").
        output_dir: Directory to write exported files.

    Returns:
        Dict mapping format name → output file path.
    """
    if not os.path.isfile(audio_path):
        raise AssemblyError(f"Source audio not found: {audio_path}")

    os.makedirs(output_dir, exist_ok=True)
    stem = Path(audio_path).stem
    results: dict[str, str] = {}

    format_configs = {
        "mp3": {
            "ext": ".mp3",
            "args": ["-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2"],
            "desc": "MP3 128kbps CBR 44.1kHz",
        },
        "m4b": {
            "ext": ".m4b",
            "args": ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-vn"],
            "desc": "M4B AAC",
        },
        "wav": {
            "ext": ".wav",
            "args": ["-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2"],
            "desc": "WAV 24-bit 48kHz",
        },
    }

    for fmt in formats:
        fmt_lower = fmt.lower().strip()
        if fmt_lower not in format_configs:
            logger.warning("Unsupported export format '%s', skipping", fmt)
            continue

        config = format_configs[fmt_lower]
        out_path = os.path.join(output_dir, f"{stem}{config['ext']}")
        args = ["-i", audio_path] + config["args"]

        logger.info("Exporting %s → %s", config["desc"], out_path)
        _run_ffmpeg(args + [out_path], description=f"Export {config['desc']}")
        results[fmt_lower] = out_path

    logger.info("Exported %d formats to %s", len(results), output_dir)
    return results


def _safe_unlink(path: str) -> None:
    """Remove a file if it exists, ignoring errors."""
    try:
        os.unlink(path)
    except OSError:
        pass
