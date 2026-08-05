"""Shared data models for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class PipelineState(str, Enum):
    """The twelve states of the pipeline state machine.

    Transition table (source → allowed destinations):
        NOT_STARTED → INGESTING
        INGESTING → VOICE_CASTING | FAILED
        VOICE_CASTING → PREFLIGHT | FAILED
        PREFLIGHT → PILOTING | FAILED
        PILOTING → SYNTHESIZING | FAILED
        SYNTHESIZING → QC | FAILED
        QC → MASTERING | FAILED
        MASTERING → PACKAGING | FAILED
        PACKAGING → DISTRIBUTING | FAILED
        DISTRIBUTING → COMPLETED | FAILED
        COMPLETED → (terminal)
        FAILED → (terminal)
    """

    NOT_STARTED = "not_started"
    INGESTING = "ingesting"
    VOICE_CASTING = "voice_casting"
    PREFLIGHT = "preflight"
    PILOTING = "piloting"
    SYNTHESIZING = "synthesizing"
    QC = "qc"
    MASTERING = "mastering"
    PACKAGING = "packaging"
    DISTRIBUTING = "distributing"
    COMPLETED = "completed"
    FAILED = "failed"


# Canonical transition table
TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.NOT_STARTED: {PipelineState.INGESTING},
    PipelineState.INGESTING: {PipelineState.VOICE_CASTING, PipelineState.FAILED},
    PipelineState.VOICE_CASTING: {PipelineState.PREFLIGHT, PipelineState.FAILED},
    PipelineState.PREFLIGHT: {PipelineState.PILOTING, PipelineState.FAILED},
    PipelineState.PILOTING: {PipelineState.SYNTHESIZING, PipelineState.FAILED},
    PipelineState.SYNTHESIZING: {PipelineState.QC, PipelineState.FAILED},
    PipelineState.QC: {PipelineState.MASTERING, PipelineState.FAILED},
    PipelineState.MASTERING: {PipelineState.PACKAGING, PipelineState.FAILED},
    PipelineState.PACKAGING: {PipelineState.DISTRIBUTING, PipelineState.FAILED},
    PipelineState.DISTRIBUTING: {PipelineState.COMPLETED, PipelineState.FAILED},
    PipelineState.COMPLETED: set(),  # terminal
    PipelineState.FAILED: set(),     # terminal
}


class CheckpointAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    SKIP = "skip"  # only valid for waivable checkpoints in auto_mode


@dataclass
class Checkpoint:
    """A mandatory human checkpoint."""

    stage: int
    task: str
    description: str
    waivable: bool = False
    action: CheckpointAction | None = None
    timestamp: str | None = None


@dataclass
class StageResult:
    """Result produced by each stage's execution."""

    stage: int
    state: PipelineState
    started_at: str = ""
    completed_at: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    checkpoint: Checkpoint | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        if self.checkpoint:
            d["checkpoint"]["action"] = (
                self.checkpoint.action.value if self.checkpoint.action else None
            )
        return d


@dataclass
class RunState:
    """The full persisted state of a pipeline run."""

    run_id: str
    manuscript_path: str
    state: PipelineState = PipelineState.NOT_STARTED
    auto_mode: bool = True
    created_at: str = field(default_factory=lambda: _utcnow())
    updated_at: str = field(default_factory=lambda: _utcnow())
    stage_results: dict[int, StageResult] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manuscript_path": self.manuscript_path,
            "state": self.state.value,
            "auto_mode": self.auto_mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stage_results": {
                str(k): v.to_dict() for k, v in self.stage_results.items()
            },
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
