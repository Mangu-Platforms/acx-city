# FOUND — out-of-plan findings

Running log of defects noticed during remediation that were outside the active
phase's scope (ground rule 5), plus places where reality contradicted the plan.

## 2026-08-12 verification session

Context: the P0.0–P0.8 program was already executed and committed on 2026-08-08
(`428aad8` → `39989c3`, plus post-P0 fixes `784c3ed`–`2c817cc`). This session
re-ran every exit gate against the current checkout.

### Fixed this session

1. **Frontend build was red on main.** `VoiceCatalog.tsx:317` — untyped `ab`
   callback parameter (TS7006), introduced by `6cb59d4` (workflow-review fixes
   committed without rerunning `npm run build`). Fixed with an explicit
   `ArrayBuffer` annotation.
2. **Dead `v1-api` service in `docker-compose.yml`.** It launched
   `uvicorn v1_api:app` against the module deleted in P0.3 (`0895579`), so
   `docker compose up` would crash-loop that service. Removed the block —
   this was a P0.3 spec item that had been missed.
3. **`fastapi` still pinned in `backend/requirements.txt`.** Nothing has
   imported it since P0.3. Removed.

### Spec errors (plan was wrong; code wins)

- **P0.3 said to remove `uvicorn` — spec error, confirmed by the author
  2026-08-12.** `backend/mcp_server.py` (MCP operator server, added after the
  plan was written) imports it lazily in `main()`. Kept; the requirements
  comment documents this.

### Deviations from the plan

- The plan's named tests (`test_chapter_audio_survives_local_disk_wipe`,
  `test_lease_renewal_independent_of_chapter_progress`,
  `test_worker_a_cannot_cancel_job_claimed_by_worker_b`) were implemented
  under different names: see `tests/test_jobs.py`
  (`test_orphan_recovery_requeues_dead_worker_job`,
  `test_restart_resumes_completed_chapters`, `test_cancel_queued_job`) and
  the `test_e2e_*` suites.

## 2026-08-12 (later): P0.8 gate determination — the gate was not met

**Plainly: P0.8 should not have been marked complete.** Two independent
failures, either of which alone invalidates the gate as specified:

1. **The golden-path test never asserts decodability — option (1) of the
   three-way determination.** There is no ffprobe/decode assertion to skip and
   nothing upstream fabricates a valid artifact. The `stub_pipeline` fixture
   (`tests/conftest.py:88-139`) monkeypatches the entire audio layer: provider
   `synthesize` (returns `b"ID3fake..."` literals), `merge_audio_files`
   (writes `b"ID3merged"`), `export_m4b` (writes `b"M4Bfake"`),
   `concat_audio_files` (writes `b"ID3concat"`), `normalize_audio` (returns
   False), and `qc_check` — patched on both the `AudioUtils` staticmethod and
   the `jobs.pipeline._audio` singleton — to unconditionally return
   `passed: True, duration_s: 12.0` without decoding anything. The E2E suite
   honestly exercises HTTP surface, ownership, DB state machine, worker claim/
   resume, billing idempotency, and storage keys — but no test anywhere
   verifies that produced audio decodes. Two tests assert the *fake* bytes
   verbatim (`test_e2e_voice_catalog.py:300-302`,
   `test_e2e_streaming.py:280`).
2. **"In CI" never happened — GitHub Actions is billing-locked.** Every CI
   run in the visible history (2026-08-07 through today) failed with **zero
   steps executed**; check-run annotation: "The job was not started because
   your account is locked due to a billing issue." This includes every P0
   phase commit. Every P0 exit gate that passed, passed locally only. CI has
   never once executed on this program's work.

Consequences: `FakeSpeechProvider` emits 23 undecodable bytes (`b"ID3fake"`
+ 16 digest bytes) — the P0.7 spec's "real, decodable" requirement was also
unmet. The capability matrix's E2E column is soft wherever a capability's
essence is audio output. Remediation sequence: P1.0 (decodable deterministic
fake + shaped failure modes) → re-run P0.8 with a live decodability assertion
→ matrix re-audit demoting rows whose E2E passed undecodable bytes → P1.1.

### Deploy provenance (checked 2026-08-12)

- **Vercel: confirmed this repo, branch `main`.** Project `acx-city`
  (domains: coverlabs.app, www.coverlabs.app) started a production deployment
  at 17:49:32Z — one second after the push of `e27e662` — and exposes a
  `git-main` alias. Deployment reached READY. A second project
  `acx-city-gmlo` is a stale duplicate (latest deployment 2026-08-05,
  preview-only, no custom domains) — candidate for deletion, user's call.
- **Railway: unverifiable from the working copy.** The `railway.toml` files
  configure build/run only; the repo/branch link lives in Railway's dashboard
  (Service → Settings → Source). User must eyeball it.

### Open items (need user action or a later phase)

1. **P0.4 CI enforcement missing.** `python scripts/gen_ts_types.py --check`
   is not in `.github/workflows/ci.yml` — the local change could not be pushed
   because the GitHub OAuth token lacks `workflow` scope. Resolution chosen
   2026-08-12: no PAT; the exact step to paste via the GitHub UI is in
   `CI_STEP_TO_ADD.yml` (backend job, after "Lint (ruff)"). Until pasted,
   drift between contracts and `api.generated.ts` will not fail CI (verified
   in sync as of 2026-08-12).
2. **Branch protection** (P0.1 manual step) — set in the GitHub UI; cannot be
   verified from the working copy.
3. **P0.5 chaos gate not automated.** "kill -9 at 20+ random points" exists as
   unit/integration coverage of lease, orphan-recovery, and terminal-guard
   logic — not as a scripted chaos test.
4. **EPUB test warning.** `UserWarning: Duplicate name: 'EPUB/cover.xhtml'`
   during EPUB tests — the generator writes a duplicate zip entry. Harmless
   but worth a look in a later EPUB pass.
5. **Dependabot: 70 open vulnerabilities** (1 critical, 29 high, 36 moderate,
   4 low) reported on push 2026-08-12. Security audit is explicitly out of
   remediation scope (ground rules); needs its own pass. The single critical:
   **CVE-2026-47429 — `vitest` (`frontend/package-lock.json`, scope:
   development)** — arbitrary file read/execute when the Vitest UI dev server
   is listening. Dev/build dependency only; not in the synthesis or storage
   runtime path, so no runtime-correctness exposure. Deferred with the rest.
6. **GitHub Actions billing lock (user action).** All CI is dead until the
   account lock is cleared — see the P0.8 determination above. Branch
   protection on the three checks is meaningless while jobs cannot start.
6. **State-verification note (2026-08-12).** An independent clone reportedly
   showed the pre-remediation tree (v1_api present, red builds) on the same
   day that `git ls-remote` returned `main = 2c817cc` (post-remediation).
   The remote was verified live from this machine; the conflicting clone was
   most likely a fork or a stale local copy. Unresolved which.
