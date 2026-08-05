"""Append-only JSONL run log for observability and crash-resume reconstruction."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunLog:
    """Append-only structured log. One JSON object per line."""

    def __init__(self, run_root: Path):
        self.path = run_root / "run.log.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create if missing
        if not self.path.exists():
            self.path.touch()

    def append(self, event: str, **data: Any) -> None:
        """Append a single log entry. Thread-safe via O_APPEND."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **data,
        }
        line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read_all(self) -> list[dict[str, Any]]:
        """Read all entries (for crash-resume reconstruction)."""
        entries = []
        if not self.path.exists():
            return entries
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Filter entries for a specific run_id."""
        return [e for e in self.read_all() if e.get("run_id") == run_id]

    def last_event(self) -> dict[str, Any] | None:
        """Return the most recent log entry."""
        entries = self.read_all()
        return entries[-1] if entries else None
