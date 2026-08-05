"""Tests for the state machine and persistence."""

import json
import pytest
from pathlib import Path
from pipeline.models import PipelineState
from pipeline.state import (
    init_run,
    load_state,
    save_state,
    transition_to,
    validate_transition,
    StateMachineError,
)


def test_valid_transitions():
    """All transitions in the table should be accepted."""
    valid = [
        (PipelineState.NOT_STARTED, PipelineState.INGESTING),
        (PipelineState.INGESTING, PipelineState.VOICE_CASTING),
        (PipelineState.INGESTING, PipelineState.FAILED),
        (PipelineState.VOICE_CASTING, PipelineState.PREFLIGHT),
        (PipelineState.PREFLIGHT, PipelineState.PILOTING),
        (PipelineState.PILOTING, PipelineState.SYNTHESIZING),
        (PipelineState.SYNTHESIZING, PipelineState.QC),
        (PipelineState.QC, PipelineState.MASTERING),
        (PipelineState.MASTERING, PipelineState.PACKAGING),
        (PipelineState.PACKAGING, PipelineState.DISTRIBUTING),
        (PipelineState.DISTRIBUTING, PipelineState.COMPLETED),
        (PipelineState.DISTRIBUTING, PipelineState.FAILED),
    ]
    for current, target in valid:
        validate_transition(current, target)  # Should not raise


def test_invalid_transitions():
    """Invalid transitions should raise StateMachineError."""
    invalid = [
        (PipelineState.COMPLETED, PipelineState.INGESTING),
        (PipelineState.FAILED, PipelineState.QC),
        (PipelineState.QC, PipelineState.INGESTING),
        (PipelineState.NOT_STARTED, PipelineState.COMPLETED),
    ]
    for current, target in invalid:
        with pytest.raises(StateMachineError):
            validate_transition(current, target)


def test_init_and_load(tmp_path):
    """Init creates state.json; load reads it back."""
    run_root = tmp_path / "test_run"
    run = init_run(run_root, "/path/to/manuscript.txt")
    assert run.state == PipelineState.NOT_STARTED
    assert run.manuscript_path == "/path/to/manuscript.txt"

    loaded = load_state(run_root)
    assert loaded.run_id == run.run_id
    assert loaded.state == PipelineState.NOT_STARTED
    assert loaded.manuscript_path == "/path/to/manuscript.txt"


def test_atomic_save(tmp_path):
    """State file should have a valid checksum."""
    run_root = tmp_path / "test_run"
    run = init_run(run_root, "/test.txt")

    data = json.loads((run_root / "state.json").read_text())
    assert "_checksum" in data


def test_transition_persists(tmp_path):
    """Transition should update state.json on disk."""
    run_root = tmp_path / "test_run"
    run = init_run(run_root, "/test.txt")

    transition_to(run, PipelineState.INGESTING, run_root)
    assert run.state == PipelineState.INGESTING

    loaded = load_state(run_root)
    assert loaded.state == PipelineState.INGESTING


def test_init_fails_if_exists(tmp_path):
    """Cannot init twice in the same directory."""
    run_root = tmp_path / "test_run"
    init_run(run_root, "/test.txt")
    with pytest.raises(StateMachineError, match="already exists"):
        init_run(run_root, "/test.txt")


def test_corrupt_state_fails(tmp_path):
    """Corrupted state.json should raise."""
    run_root = tmp_path / "test_run"
    run_root.mkdir()
    (run_root / "state.json").write_text("{corrupt json")
    with pytest.raises(Exception):
        load_state(run_root)
