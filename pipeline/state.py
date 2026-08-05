"""State machine with atomic persistence and crash-resume."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .models import PipelineState, RunState, StageResult, TRANSITIONS


class StateMachineError(Exception):
    """Raised on invalid state transitions or persistence failures."""

    def __init__(self, message: str, current: PipelineState | None = None,
                 attempted: PipelineState | None = None):
        self.current = current
        self.attempted = attempted
        super().__init__(message)


def validate_transition(current: PipelineState, target: PipelineState) -> None:
    """Raise if current → target is not in the transition table."""
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        raise StateMachineError(
            f"Invalid transition: {current.value} → {target.value}. "
            f"Allowed: {[s.value for s in allowed] or '(terminal)'}",
            current=current,
            attempted=target,
        )


def load_state(run_root: Path) -> RunState:
    """Load state.json from the run root. Raises if missing or corrupt."""
    state_path = run_root / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"No state.json found at {state_path}")

    raw = state_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    # Verify integrity if checksum present
    if "_checksum" in data:
        expected = data.pop("_checksum")
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        actual = hashlib.sha256(content.encode()).hexdigest()[:16]
        if actual != expected:
            raise StateMachineError(
                f"state.json checksum mismatch: expected {expected}, got {actual}. "
                "State file may be corrupt. Check backups."
            )

    # Reconstruct typed objects
    data["state"] = PipelineState(data["state"])
    stage_results = {}
    for k, v in data.get("stage_results", {}).items():
        v["state"] = PipelineState(v["state"])
        if v.get("checkpoint") and v["checkpoint"].get("action"):
            from .models import CheckpointAction
            v["checkpoint"]["action"] = CheckpointAction(v["checkpoint"]["action"])
        stage_results[int(k)] = StageResult(**v)
    data["stage_results"] = stage_results

    return RunState(**data)


def save_state(run_state: RunState, run_root: Path) -> None:
    """Atomically persist state.json (write-temp, fsync, rename).

    This guarantees that a crash during write never produces a half-written file.
    """
    run_root.mkdir(parents=True, exist_ok=True)
    state_path = run_root / "state.json"
    data = run_state.to_dict()

    # Compute checksum
    content = json.dumps(data, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(content.encode()).hexdigest()[:16]
    data["_checksum"] = checksum

    # Write to temp file on same filesystem
    fd, tmp_path = tempfile.mkstemp(
        dir=str(run_root), suffix=".tmp", prefix="state_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename (same filesystem)
        os.replace(tmp_path, state_path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def transition_to(
    run_state: RunState,
    target: PipelineState,
    run_root: Path,
    *,
    stage: int | None = None,
    error: str | None = None,
) -> RunState:
    """Execute a validated transition and persist atomically.

    Returns the updated RunState (also mutated in place).
    """
    from .models import _utcnow

    validate_transition(run_state.state, target)

    run_state.state = target
    run_state.updated_at = _utcnow()

    if stage is not None and target == PipelineState.FAILED:
        sr = run_state.stage_results.get(stage)
        if sr:
            sr.state = PipelineState.FAILED
            sr.error = error
            sr.completed_at = _utcnow()

    save_state(run_state, run_root)
    return run_state


def init_run(run_root: Path, manuscript_path: str, auto_mode: bool = True) -> RunState:
    """Create a fresh run state and persist it. Fails if state.json already exists."""
    state_path = run_root / "state.json"
    if state_path.exists():
        raise StateMachineError(
            f"state.json already exists at {state_path}. "
            "Use load_state() to resume, or delete the file to start fresh."
        )

    import uuid
    run = RunState(
        run_id=str(uuid.uuid4()),
        manuscript_path=manuscript_path,
        auto_mode=auto_mode,
    )
    save_state(run, run_root)
    return run
