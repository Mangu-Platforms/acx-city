"""Content-addressed synthesis cache — guarantees no duplicate billable synthesis.

The cache key is: SHA256(text_chunk + voice_hash + engine + config_hash).
If a cache hit exists, synthesis is skipped entirely. This is the mechanism
that prevents "a crash never causes a duplicate billable synthesis" (Section IV).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SynthesisCache:
    """Content-addressed cache for synthesis results."""

    def __init__(self, run_root: Path):
        self.cache_dir = run_root / "synthesis_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index()

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return {}

    def _save_index(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.index_path)

    @staticmethod
    def _make_key(
        text: str,
        voice_hash: str,
        engine: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Generate a deterministic content-addressed cache key."""
        parts = {
            "text": text,
            "voice": voice_hash,
            "engine": engine,
            "config": config or {},
        }
        canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def lookup(
        self,
        text: str,
        voice_hash: str,
        engine: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return cached result or None."""
        key = self._make_key(text, voice_hash, engine, config)
        return self._index.get(key)

    def store(
        self,
        text: str,
        voice_hash: str,
        engine: str,
        config: dict[str, Any] | None,
        result: dict[str, Any],
    ) -> str:
        """Store a synthesis result. Returns the cache key."""
        key = self._make_key(text, voice_hash, engine, config)
        self._index[key] = {
            "result": result,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "text_length": len(text),
        }
        self._save_index()
        return key

    @property
    def size(self) -> int:
        return len(self._index)

    def clear(self) -> int:
        """Clear the cache. Returns number of entries removed."""
        count = len(self._index)
        self._index = {}
        self._save_index()
        return count
