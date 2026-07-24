import os
import subprocess
from typing import Dict, List

from pydub import AudioSegment
from pydub.silence import detect_silence


class AudioUtils:
    @staticmethod
    def merge_audio_files(file_paths: List[str], output_path: str, gap_duration: int = 1000) -> bool:
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
            print(f"Error merging audio files: {e}")
            return False

    @staticmethod
    def normalize_audio(input_path: str, output_path: str, target_dBFS: float = -20.0) -> bool:
        try:
            audio = AudioSegment.from_file(input_path)
            normalized = audio.apply_gain(target_dBFS - audio.dBFS)
            normalized.export(output_path, format="mp3")
            return True
        except Exception as e:
            print(f"Error normalizing audio: {e}")
            return False

    @staticmethod
    def qc_check(file_path: str) -> Dict:
        """Basic quality checks on a chapter file.

        Returns duration, loudness, silence ratio, clipping flag, and a list
        of human-readable issues (empty list == passed).
        """
        audio = AudioSegment.from_file(file_path)
        duration_s = len(audio) / 1000.0
        issues = []

        if duration_s < 1.0:
            issues.append("Audio is under 1 second — synthesis likely failed")

        loudness = audio.dBFS if duration_s > 0 else float("-inf")
        if loudness != float("-inf") and loudness < -40:
            issues.append(f"Very quiet audio ({loudness:.1f} dBFS)")

        peak = audio.max_dBFS if duration_s > 0 else float("-inf")
        clipping = peak > -0.1
        if clipping:
            issues.append("Possible clipping (peak at 0 dBFS)")

        silence_ratio = 0.0
        if duration_s > 0:
            silent_ranges = detect_silence(audio, min_silence_len=2000, silence_thresh=-45)
            silent_ms = sum(end - start for start, end in silent_ranges)
            silence_ratio = silent_ms / len(audio)
            if silence_ratio > 0.4:
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
            # Build ffmpeg concat list + chapter metadata
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

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_path,
                "-i", meta_path, "-map_metadata", "1",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                "-f", "mp4", output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            for tmp in (concat_path, meta_path):
                try:
                    os.remove(tmp)
                except OSError:
                    pass  # cleanup is best-effort; never fail the export over it
            if result.returncode != 0:
                print(f"ffmpeg m4b export failed: {result.stderr[-2000:]}")
                return False
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            print(f"Error exporting m4b: {e}")
            return False
