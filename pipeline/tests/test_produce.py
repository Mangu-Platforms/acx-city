"""Integration test for the orchestrator with a real manuscript."""

import pytest
from pathlib import Path
from pipeline.state import init_run, load_state
from pipeline.models import PipelineState
from pipeline.produce import ProduceOrchestrator


@pytest.fixture
def sample_manuscript(tmp_path):
    """Create a sample manuscript for testing."""
    manuscript = tmp_path / "manuscript.txt"
    manuscript.write_text("""Chapter 1: Test

This is a test chapter with enough content to process.

Chapter 2: Another

More content here for testing purposes.
""")
    return manuscript


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / "runs"


def test_full_ingestion(tmp_path, sample_manuscript, run_dir):
    """Test that ingestion stage runs end-to-end."""
    run_root = run_dir / "test_run"
    run = init_run(run_root, str(sample_manuscript), auto_mode=True)

    orch = ProduceOrchestrator(run, run_root)

    # Step once — should go from NOT_STARTED to INGESTING
    orch._step()
    assert run.state == PipelineState.INGESTING

    # Step again — should ingest and move to VOICE_CASTING
    orch._step()
    assert run.state == PipelineState.VOICE_CASTING

    # Verify artifacts exist
    assert (run_root / "artifacts" / "stage_0" / "scrubbed.txt").exists()
    assert (run_root / "artifacts" / "stage_0" / "chapter_manifest.json").exists()

    # Step again — runs the stage-1 placeholder
    orch._step()

    # Verify state persisted
    loaded = load_state(run_root)
    assert loaded.state == PipelineState.PREFLIGHT
    assert "voice.lock" in loaded.artifacts  # Stage 1 placeholder ran


def test_crash_resume(tmp_path, sample_manuscript, run_dir):
    """Test that we can resume after a crash at a specific state."""
    run_root = run_dir / "resume_test"
    run = init_run(run_root, str(sample_manuscript), auto_mode=True)

    orch = ProduceOrchestrator(run, run_root)
    orch._step()  # → INGESTING
    orch._step()  # → VOICE_CASTING
    orch._step()  # → PREFLIGHT
    orch._step()  # → PILOTING

    # Simulate crash: reload from disk
    reloaded = load_state(run_root)
    assert reloaded.state == PipelineState.PILOTING

    orch2 = ProduceOrchestrator(reloaded, run_root)
    # Should resume from PILOTING, not restart
    assert reloaded.state == PipelineState.PILOTING
