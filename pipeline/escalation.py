"""Escalation directory protocol for checkpoint management."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Checkpoint, CheckpointAction


class EscalationDir:
    """Manages the checkpoints/ directory for human interaction.

    In daemon mode, checkpoints are written as files in the checkpoints/ directory.
    The operator (or ops dashboard) picks them up, writes a response file, and the
    pipeline resumes.
    """

    def __init__(self, run_root: Path):
        self.dir = run_root / "checkpoints"
        self.dir.mkdir(parents=True, exist_ok=True)

    def raise_checkpoint(
        self,
        checkpoint: Checkpoint,
        run_id: str,
        artifact_preview: str | None = None,
    ) -> Path:
        """Write a checkpoint request file. Returns the path written."""
        cp_id = f"s{checkpoint.stage}_{checkpoint.task}"
        request = {
            "run_id": run_id,
            "stage": checkpoint.stage,
            "task": checkpoint.task,
            "description": checkpoint.description,
            "waivable": checkpoint.waivable,
            "artifact_preview": artifact_preview,
            "raised_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        request_path = self.dir / f"{cp_id}.request.json"
        with open(request_path, "w", encoding="utf-8") as f:
            json.dump(request, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        return request_path

    def write_response(self, cp_id: str, action: CheckpointAction, notes: str = "") -> None:
        """Write a response file for a checkpoint."""
        response = {
            "action": action.value,
            "notes": notes,
            "responded_at": datetime.now(timezone.utc).isoformat(),
        }
        response_path = self.dir / f"{cp_id}.response.json"
        with open(response_path, "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

    def poll_response(self, cp_id: str) -> dict[str, Any] | None:
        """Check if a response exists for a checkpoint."""
        response_path = self.dir / f"{cp_id}.response.json"
        if not response_path.exists():
            return None
        return json.loads(response_path.read_text(encoding="utf-8"))

    def wait_for_response(self, cp_id: str, poll_interval: float = 2.0) -> dict[str, Any]:
        """Block until a response file appears. Returns the response."""
        import time
        while True:
            resp = self.poll_response(cp_id)
            if resp is not None:
                return resp
            time.sleep(poll_interval)

    def pending_checkpoints(self) -> list[dict[str, Any]]:
        """List all checkpoints awaiting response."""
        pending = []
        for req_file in sorted(self.dir.glob("*.request.json")):
            cp_id = req_file.stem.replace(".request", "")
            resp_path = self.dir / f"{cp_id}.response.json"
            if not resp_path.exists():
                pending.append(json.loads(req_file.read_text(encoding="utf-8")))
        return pending
