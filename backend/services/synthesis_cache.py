"""Content-addressed synthesis cache.

A chunk of text synthesized with a given provider/voice/engine always produces
the same audio, so we key cached MP3s by a hash of those inputs. Re-running a
book (after an edit, a crash, or a retry) only synthesizes what changed —
unchanged text is never paid for or waited on twice.
"""
import hashlib
import os
from typing import Optional


class SynthesisCache:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    @staticmethod
    def key(provider: str, voice_id: str, engine: str, text: str) -> str:
        payload = f"{provider}|{voice_id}|{engine}|{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.mp3")

    def get(self, key: str) -> Optional[str]:
        path = self._path(key)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        return None

    def evict(self, key: str) -> None:
        """Remove a poisoned/stale entry so the next lookup re-synthesizes.

        A cache entry is an unvalidated artifact with a persistence
        guarantee; media validation (P1.1) evicts on any failed hit.
        """
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def put(self, key: str, audio: bytes) -> str:
        path = self._path(key)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(audio)
        os.replace(tmp, path)  # atomic; a crash never leaves a bad cache entry
        return path

    def stats(self) -> dict:
        files = [f for f in os.listdir(self.cache_dir) if f.endswith(".mp3")]
        total = sum(os.path.getsize(os.path.join(self.cache_dir, f)) for f in files)
        return {"entries": len(files), "bytes": total}
