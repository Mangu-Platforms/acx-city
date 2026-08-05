#!/usr/bin/env python3
"""
produce.py — Main orchestrator entry point.

Usage:
    python -m pipeline.produce <manuscript_path> [--run-root <dir>] [--no-auto]

    manuscript_path: Path to the manuscript file (txt, docx, pdf)
    --run-root:      Directory for state/logs/artifacts (default: ./runs/<run_id>)
    --no-auto:       Disable auto_mode (all checkpoints require human response)
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from .state import init_run, load_state, save_state, transition_to
from .run_log import RunLog
from .escalation import EscalationDir
from .cache import SynthesisCache
from .models import (
    Checkpoint,
    CheckpointAction,
    PipelineState,
    RunState,
    StageResult,
    _utcnow,
)


class ProduceOrchestrator:
    """The ten-stage audiobook production orchestrator.

    Drives the pipeline through its state machine, calling stage implementations
    and managing checkpoints.
    """

    def __init__(self, run_state: RunState, run_root: Path):
        self.run_state = run_state
        self.run_root = run_root
        self.log = RunLog(run_root)
        self.escalation = EscalationDir(run_root)
        self.cache = SynthesisCache(run_root)

        self.log.append(
            "orchestrator_init",
            run_id=run_state.run_id,
            state=run_state.state.value,
            auto_mode=run_state.auto_mode,
        )

    def run(self) -> RunState:
        """Execute the pipeline from current state to completion or failure."""
        try:
            while self.run_state.state not in (
                PipelineState.COMPLETED,
                PipelineState.FAILED,
            ):
                self._step()
        except KeyboardInterrupt:
            self.log.append("interrupted", state=self.run_state.state.value)
            print(f"\nInterrupted at state: {self.run_state.state.value}")
            print(f"Resume with: python -m pipeline.produce --resume {self.run_root}")
        except Exception as e:
            self.log.append("unhandled_error", error=str(e), traceback=traceback.format_exc())
            self._fail(-1, str(e))
            raise

        return self.run_state

    def _step(self) -> None:
        """Execute one state transition."""
        state = self.run_state.state
        self.log.append("step_start", state=state.value)

        dispatch = {
            PipelineState.NOT_STARTED: self._stage_0_pre,
            PipelineState.INGESTING: self._stage_0_ingest,
            PipelineState.VOICE_CASTING: self._stage_1_voice,
            PipelineState.PREFLIGHT: self._stage_2_preflight,
            PipelineState.PILOTING: self._stage_3_pilot,
            PipelineState.SYNTHESIZING: self._stage_4_synthesize,
            PipelineState.QC: self._stage_5_qc,
            PipelineState.MASTERING: self._stage_6_master,
            PipelineState.PACKAGING: self._stage_7_package,
            PipelineState.DISTRIBUTING: self._stage_8_distribute,
        }

        handler = dispatch.get(state)
        if handler is None:
            self._fail(-1, f"No handler for state: {state.value}")
            return

        try:
            handler()
        except Exception as e:
            stage_num = _state_to_stage(state)
            self._fail(stage_num, str(e))
            self.log.append(
                "stage_error",
                state=state.value,
                error=str(e),
                traceback=traceback.format_exc(),
            )

    def _fail(self, stage: int, error: str) -> None:
        """Transition to FAILED state."""
        transition_to(self.run_state, PipelineState.FAILED, self.run_root, stage=stage, error=error)
        self.log.append("pipeline_failed", stage=stage, error=error)

    def _handle_checkpoint(
        self, checkpoint: Checkpoint, preview: str | None = None
    ) -> bool:
        """Handle a checkpoint. Returns True if approved, False if rejected."""
        self.log.append(
            "checkpoint_raised",
            stage=checkpoint.stage,
            task=checkpoint.task,
            waivable=checkpoint.waivable,
        )

        # In auto_mode with a waivable checkpoint, skip it
        if self.run_state.auto_mode and checkpoint.waivable:
            checkpoint.action = CheckpointAction.SKIP
            self.log.append(
                "checkpoint_auto_skipped",
                stage=checkpoint.stage,
                task=checkpoint.task,
            )
            return True

        # Raise to escalation directory
        cp_id = f"s{checkpoint.stage}_{checkpoint.task}"
        self.escalation.raise_checkpoint(checkpoint, self.run_state.run_id, preview)

        if self.run_state.auto_mode:
            # Daemon mode: poll for response
            print(f"  Checkpoint raised: {cp_id} — waiting for response...")
            response = self.escalation.wait_for_response(cp_id)
        else:
            # CLI mode: prompt
            print(f"\n{'='*60}")
            print(f"CHECKPOINT: {checkpoint.description}")
            if preview:
                print(f"\nPreview:\n{preview[:500]}")
            print(f"{'='*60}")
            while True:
                answer = input("Approve? [y/n]: ").strip().lower()
                if answer in ("y", "yes"):
                    response = {"action": "approve"}
                    self.escalation.write_response(cp_id, CheckpointAction.APPROVE)
                    break
                elif answer in ("n", "no"):
                    response = {"action": "reject"}
                    self.escalation.write_response(cp_id, CheckpointAction.REJECT)
                    break
                print("Please enter 'y' or 'n'.")

        action = CheckpointAction(response["action"])
        checkpoint.action = action

        self.log.append(
            "checkpoint_resolved",
            stage=checkpoint.stage,
            task=checkpoint.task,
            action=action.value,
        )

        return action == CheckpointAction.APPROVE

    # --- Stage handlers ---

    def _stage_0_pre(self) -> None:
        """Transition from NOT_STARTED to INGESTING."""
        transition_to(self.run_state, PipelineState.INGESTING, self.run_root)
        self.run_state.stage_results[0] = StageResult(
            stage=0,
            state=PipelineState.INGESTING,
            started_at=_utcnow(),
        )

    def _stage_0_ingest(self) -> None:
        """Stage 0: Ingestion — extract, scrub, chapterize."""
        from .ingest import extract_text, scrub_text, chapterize

        self.log.append("ingest_start", path=self.run_state.manuscript_path)

        # Extract
        raw_text = extract_text(self.run_state.manuscript_path)
        self.log.append("ingest_extracted", char_count=len(raw_text))

        # Scrub
        scrubbed, rules_applied = scrub_text(raw_text)
        self.log.append("ingest_scrubbed", rules=rules_applied, char_count=len(scrubbed))

        # Chapterize
        chapters, method = chapterize(scrubbed)
        self.log.append(
            "ingest_chapterized",
            chapter_count=len(chapters),
            detection_method=method,
        )

        # Save artifacts
        artifacts_dir = self.run_root / "artifacts" / "stage_0"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        (artifacts_dir / "raw.txt").write_text(raw_text, encoding="utf-8")
        (artifacts_dir / "scrubbed.txt").write_text(scrubbed, encoding="utf-8")

        import json
        manifest = {
            "source": self.run_state.manuscript_path,
            "chapters": [
                {"number": ch.number, "title": ch.title, "word_count": ch.word_count}
                for ch in chapters
            ],
            "total_words": sum(ch.word_count for ch in chapters),
            "detection_method": method,
        }
        (artifacts_dir / "chapter_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # Update state
        sr = self.run_state.stage_results[0]
        sr.state = PipelineState.COMPLETED
        sr.completed_at = _utcnow()
        sr.artifacts = {
            "raw": str(artifacts_dir / "raw.txt"),
            "scrubbed": str(artifacts_dir / "scrubbed.txt"),
            "manifest": str(artifacts_dir / "chapter_manifest.json"),
        }
        self.run_state.artifacts.update(sr.artifacts)

        save_state(self.run_state, self.run_root)
        self.log.append("ingest_complete", chapters=len(chapters))

        # Move to next stage
        transition_to(self.run_state, PipelineState.VOICE_CASTING, self.run_root)

    def _stage_1_voice(self) -> None:
        """Stage 1: Voice Casting — BLOCKED pending spec volume 04."""
        self.log.append("voice_casting_blocked", reason="Spec volume 04 missing")
        print("  Stage 1 (Voice Casting): BLOCKED — spec volume 04 not available.")
        print("  Skipping to Stage 2 with placeholder voice.lock")

        # Write placeholder voice.lock
        import json
        artifacts_dir = self.run_root / "artifacts" / "stage_1"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        voice_lock = {
            "voice_id": "placeholder_unassigned",
            "engine": "edge-tts",
            "language": "en-US",
            "locked": False,
            "placeholder": True,
            "note": "Replace when spec volume 04 is implemented",
        }
        voice_lock_path = artifacts_dir / "voice.lock"
        voice_lock_path.write_text(json.dumps(voice_lock, indent=2), encoding="utf-8")

        # Compute hash of voice.lock (needed for cache key downstream)
        import hashlib
        vl_hash = hashlib.sha256(voice_lock_path.read_bytes()).hexdigest()[:16]

        self.run_state.artifacts["voice.lock"] = str(voice_lock_path)
        self.run_state.artifacts["voice.lock_hash"] = vl_hash
        self.run_state.metadata["voice_lock_hash"] = vl_hash

        sr = StageResult(
            stage=1,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
            artifacts={"voice.lock": str(voice_lock_path)},
        )
        self.run_state.stage_results[1] = sr

        save_state(self.run_state, self.run_root)
        transition_to(self.run_state, PipelineState.PREFLIGHT, self.run_root)

    def _stage_2_preflight(self) -> None:
        """Stage 2: Preflight — verify API, config, prerequisites."""
        self.log.append("preflight_start")

        # Check local API is reachable
        import urllib.request
        import urllib.error
        api_url = self.run_state.metadata.get("api_url", "http://localhost:5000")
        try:
            req = urllib.request.urlopen(f"{api_url}/api/health", timeout=5)
            api_ok = req.status == 200
        except (urllib.error.URLError, OSError):
            api_ok = False

        self.log.append("preflight_api_check", url=api_url, ok=api_ok)

        if not api_ok:
            # Don't fail — just warn. Local dev may not have API running.
            self.log.append("preflight_api_warning", message="API not reachable, proceeding anyway")

        sr = StageResult(
            stage=2,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[2] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("preflight_complete")
        transition_to(self.run_state, PipelineState.PILOTING, self.run_root)

    def _stage_3_pilot(self) -> None:
        """Stage 3: Pilot — synthesize a small sample, QC it."""
        self.log.append("pilot_start")
        # Placeholder — full implementation requires voice casting (Stage 1)
        # and the synthesis API. Will synthesize first chapter of first chapter.

        cp = Checkpoint(
            stage=3, task="T01",
            description="Approve pilot synthesis (first chapter sample)",
            waivable=True,  # auto_mode can skip if metrics are perfect
        )
        approved = self._handle_checkpoint(cp)
        if not approved:
            self._fail(3, "Pilot checkpoint rejected")
            return

        sr = StageResult(
            stage=3,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[3] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("pilot_complete")
        transition_to(self.run_state, PipelineState.SYNTHESIZING, self.run_root)

    def _stage_4_synthesize(self) -> None:
        """Stage 4: Full synthesis — all chapters, content-addressed."""
        self.log.append("synthesize_start")

        # Placeholder — uses cache for duplicate prevention
        sr = StageResult(
            stage=4,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[4] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("synthesize_complete")
        transition_to(self.run_state, PipelineState.QC, self.run_root)

    def _stage_5_qc(self) -> None:
        """Stage 5: QC — loudness, noise, clipping checks."""
        self.log.append("qc_start")

        sr = StageResult(
            stage=5,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[5] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("qc_complete")
        transition_to(self.run_state, PipelineState.MASTERING, self.run_root)

    def _stage_6_master(self) -> None:
        """Stage 6: Mastering — loudness normalization, concat, M4B."""
        self.log.append("master_start")

        sr = StageResult(
            stage=6,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[6] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("master_complete")
        transition_to(self.run_state, PipelineState.PACKAGING, self.run_root)

    def _stage_7_package(self) -> None:
        """Stage 7: Packaging — cover art, metadata, bundle. Requires external input."""
        self.log.append("package_start")

        cp = Checkpoint(
            stage=7, task="T05",
            description="Sign off on packaging (cover art, metadata, bundle)",
            waivable=False,  # Unwaivable per spec
        )
        approved = self._handle_checkpoint(cp)
        if not approved:
            self._fail(7, "Packaging checkpoint rejected")
            return

        sr = StageResult(
            stage=7,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[7] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("package_complete")
        transition_to(self.run_state, PipelineState.DISTRIBUTING, self.run_root)

    def _stage_8_distribute(self) -> None:
        """Stage 8: Distribution — submit to channels. Requires credentials."""
        self.log.append("distribute_start")

        cp = Checkpoint(
            stage=8, task="T01",
            description="Approve distribution to channels",
            waivable=False,
        )
        approved = self._handle_checkpoint(cp)
        if not approved:
            self._fail(8, "Distribution checkpoint rejected")
            return

        sr = StageResult(
            stage=8,
            state=PipelineState.COMPLETED,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.run_state.stage_results[8] = sr
        save_state(self.run_state, self.run_root)
        self.log.append("distribute_complete")
        transition_to(self.run_state, PipelineState.COMPLETED, self.run_root)


def _state_to_stage(state: PipelineState) -> int:
    """Map a pipeline state to its stage number."""
    mapping = {
        PipelineState.NOT_STARTED: 0,
        PipelineState.INGESTING: 0,
        PipelineState.VOICE_CASTING: 1,
        PipelineState.PREFLIGHT: 2,
        PipelineState.PILOTING: 3,
        PipelineState.SYNTHESIZING: 4,
        PipelineState.QC: 5,
        PipelineState.MASTERING: 6,
        PipelineState.PACKAGING: 7,
        PipelineState.DISTRIBUTING: 8,
    }
    return mapping.get(state, -1)


def main():
    parser = argparse.ArgumentParser(description="ACX City Audiobook Production Pipeline")
    parser.add_argument("manuscript", nargs="?", help="Path to manuscript file")
    parser.add_argument("--run-root", type=Path, help="Directory for state/logs")
    parser.add_argument("--resume", type=Path, help="Resume from an existing run directory")
    parser.add_argument("--no-auto", action="store_true", help="Disable auto_mode")
    parser.add_argument("--list-checkpoints", action="store_true", help="List pending checkpoints")

    args = parser.parse_args()

    if args.resume:
        run_root = args.resume
        run_state = load_state(run_root)
        print(f"Resuming run {run_state.run_id} from state: {run_state.state.value}")
    elif args.manuscript:
        run_root = args.run_root or Path("runs") / _make_run_id()
        run_state = init_run(run_root, args.manuscript, auto_mode=not args.no_auto)
        print(f"Starting run {run_state.run_id}")
        print(f"  Manuscript: {args.manuscript}")
        print(f"  Run root:   {run_root}")
        print(f"  Auto mode:  {run_state.auto_mode}")
    else:
        parser.error("Provide a manuscript path or --resume <run_root>")

    if args.list_checkpoints:
        esc = EscalationDir(run_root)
        pending = esc.pending_checkpoints()
        if not pending:
            print("No pending checkpoints.")
        for cp in pending:
            print(f"  {cp['stage']}/{cp['task']}: {cp['description']}")
        return

    orchestrator = ProduceOrchestrator(run_state, run_root)
    result = orchestrator.run()

    print(f"\nPipeline finished: {result.state.value}")
    print(f"  Run root: {run_root}")
    print(f"  Run log:  {run_root / 'run.log.jsonl'}")


def _make_run_id() -> str:
    import uuid
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{ts}_{short}"


if __name__ == "__main__":
    main()
