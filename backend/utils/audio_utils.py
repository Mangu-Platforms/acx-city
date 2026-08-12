import logging
import os
import subprocess
from typing import Dict, List

from pydub import AudioSegment
from pydub.silence import detect_silence

log = logging.getLogger("audiobook.audio")

# Silence detection tuned for TTS audiobook output.
# -55 dBFS threshold avoids false positives from breath-level noise between
# sentences. 3 s minimum avoids counting normal paragraph pauses as silence.
_SILENCE_THRESH_DBFS = -55
_SILENCE_MIN_LEN_MS = 3000
_SILENCE_RATIO_WARN = 0.55   # >55% silence is suspicious for an audiobook chapter

# Loudness warning threshold: TTS engines typically output -18 to -23 dBFS.
# Flag only genuinely inaudible levels.
_LOUDNESS_WARN_DBFS = -45

# ACX-compatible normalization target (midpoint of -18 to -23 LUFS range).
_NORMALIZE_TARGET_DBFS = -20.0

# Spoken-English pacing: ~150 words/min ≈ 12.5 chars/sec. Single source of
# truth for anything that maps character counts to audio durations (streaming
# preview truncation, fake-provider duration law, duration-plausibility QC).
CHARS_PER_SECOND = 12.5


class AudioUtils:
    @staticmethod
    def merge_audio_files(file_paths: List[str], output_path: str, gap_duration: int = 1000) -> bool:
        """Merge MP3 files via pydub with a silence gap between each.

        Used for intra-chapter chunk assembly. For the final inter-chapter
        merge prefer concat_audio_files to avoid a second encode cycle.
        """
        if not file_paths:
            return False
        try:
            combined = AudioSegment.empty()
            for i, file_path in enumerate(file_paths):
                if os.path.exists(file_path):
                    combined += AudioSegment.from_file(file_path)
                    if i < len(file_paths) - 1:
                        combined += AudioSegment.silent(duration=gap_duration)
            combined.export(output_path, format="mp3", bitrate="128k")
            return True
        except Exception as e:
            log.exception("error merging audio files: %s", e)
            return False

    @staticmethod
    def concat_audio_files(file_paths: List[str], output_path: str, gap_ms: int = 1500) -> bool:
        """Concatenate already-normalized chapter MP3s using ffmpeg concat demuxer.

        Fix #3: avoids a second pydub encode/decode generation-loss cycle for
        the final book assembly. A silent gap is inserted between chapters by
        generating a short silent MP3 and interleaving it via the concat list.
        """
        if not file_paths:
            return False

        base = os.path.splitext(output_path)[0]
        concat_path = base + "_concat.txt"
        gap_path = base + "_gap.mp3"

        try:
            # Generate the inter-chapter silence clip once.
            AudioSegment.silent(duration=gap_ms).export(gap_path, format="mp3", bitrate="128k")

            with open(concat_path, "w") as f:
                for i, path in enumerate(file_paths):
                    f.write(f"file '{os.path.abspath(path)}'\n")
                    if i < len(file_paths) - 1:
                        f.write(f"file '{os.path.abspath(gap_path)}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_path,
                "-c", "copy",          # stream-copy: no re-encode, no generation loss
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                log.error("ffmpeg concat failed: %s", result.stderr[-2000:])
                return False
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            log.exception("error concatenating audio files: %s", e)
            return False
        finally:
            for tmp in (concat_path, gap_path):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    @staticmethod
    def normalize_audio(input_path: str, output_path: str, target_dBFS: float = _NORMALIZE_TARGET_DBFS) -> bool:
        """Normalize audio to a consistent loudness target (default -20 dBFS).

        Fix #2: called per-chapter in the pipeline so all chapters in a book
        have uniform volume regardless of TTS output level.
        """
        try:
            audio = AudioSegment.from_file(input_path)
            if audio.dBFS == float("-inf"):
                # Silent audio — don't attempt to normalize, just copy.
                audio.export(output_path, format="mp3", bitrate="128k")
                return True
            normalized = audio.apply_gain(target_dBFS - audio.dBFS)
            normalized.export(output_path, format="mp3", bitrate="128k")
            return True
        except Exception as e:
            log.exception("error normalizing audio: %s", e)
            return False

    @staticmethod
    def qc_check(file_path: str) -> Dict:
        """Quality checks on an assembled chapter file.

        Thresholds are tuned for TTS audiobook output (Fix #5):
        - Silence ratio threshold raised to 55% (from 40%) — natural paragraph
          pauses in long chapters commonly reach 30-40%.
        - Loudness warning threshold lowered to -45 dBFS (from -40) — neural
          TTS engines produce -18 to -23 dBFS; only genuinely inaudible audio
          should trigger.
        - Silence detection uses -55 dBFS and 3 s minimum to avoid counting
          normal sentence pauses as problematic silence.

        Returns duration, loudness, silence ratio, clipping flag, and a list
        of human-readable issues (empty list == passed).
        """
        audio = AudioSegment.from_file(file_path)
        duration_s = len(audio) / 1000.0
        issues = []

        if duration_s < 1.0:
            issues.append("Audio is under 1 second — synthesis likely failed")

        loudness = audio.dBFS if duration_s > 0 else float("-inf")
        if loudness != float("-inf") and loudness < _LOUDNESS_WARN_DBFS:
            issues.append(f"Very quiet audio ({loudness:.1f} dBFS)")

        peak = audio.max_dBFS if duration_s > 0 else float("-inf")
        clipping = peak > -0.1
        if clipping:
            issues.append("Possible clipping (peak at 0 dBFS)")

        silence_ratio = 0.0
        if duration_s > 0:
            silent_ranges = detect_silence(
                audio,
                min_silence_len=_SILENCE_MIN_LEN_MS,
                silence_thresh=_SILENCE_THRESH_DBFS,
            )
            silent_ms = sum(end - start for start, end in silent_ranges)
            silence_ratio = silent_ms / len(audio)
            if silence_ratio > _SILENCE_RATIO_WARN:
                issues.append(f"High silence ratio ({silence_ratio:.0%})")

        return {
            "duration_s": round(duration_s, 2),
            "loudness_dbfs": round(loudness, 1) if loudness != float("-inf") else None,
            "peak_dbfs": round(peak, 1) if peak != float("-inf") else None,
            "silence_ratio": round(silence_ratio, 3),
            "clipping": clipping,
            "issues": issues,
            "passed": not issues,
        }

    @staticmethod
    def export_m4b(chapter_files: List[str], chapter_titles: List[str], output_path: str,
                   book_title: str = "Audiobook", author: str = "") -> bool:
        """Assemble chapter MP3s into a single .m4b with chapter markers."""
        if not chapter_files:
            return False
        try:
            base = os.path.splitext(output_path)[0]
            concat_path = base + "_concat.txt"
            meta_path = base + "_meta.txt"

            with open(concat_path, "w") as f:
                for path in chapter_files:
                    f.write(f"file '{os.path.abspath(path)}'\n")

            def esc(s: str) -> str:
                return s.replace("=", r"\=").replace(";", r"\;").replace("#", r"\#").replace("\\", r"\\")

            lines = [";FFMETADATA1", f"title={esc(book_title)}"]
            if author:
                lines.append(f"artist={esc(author)}")
            start_ms = 0
            for path, title in zip(chapter_files, chapter_titles):
                dur = len(AudioSegment.from_file(path))
                lines += [
                    "[CHAPTER]", "TIMEBASE=1/1000",
                    f"START={start_ms}", f"END={start_ms + dur}",
                    f"title={esc(title)}",
                ]
                start_ms += dur
            with open(meta_path, "w") as f:
                f.write("\n".join(lines) + "\n")

            # Fix #9: cap ffmpeg timeout proportional to chapter count.
            # 60 s base + 30 s per chapter; a 20-chapter book gets 660 s max.
            timeout_s = 60 + 30 * len(chapter_files)

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_path,
                "-i", meta_path, "-map_metadata", "1",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                "-f", "mp4", output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            for tmp in (concat_path, meta_path):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if result.returncode != 0:
                log.error("ffmpeg m4b export failed: %s", result.stderr[-2000:])
                return False
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            log.exception("error exporting m4b: %s", e)
            return False
