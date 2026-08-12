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

### Deviations from the plan (code wins)

- P0.3 said to remove `uvicorn` as well — kept. `backend/mcp_server.py`
  (MCP operator server, added after the plan was written) imports it lazily
  in `main()`. The requirements comment now documents this.
- The plan's named tests (`test_chapter_audio_survives_local_disk_wipe`,
  `test_lease_renewal_independent_of_chapter_progress`,
  `test_worker_a_cannot_cancel_job_claimed_by_worker_b`) were implemented
  under different names: see `tests/test_jobs.py`
  (`test_orphan_recovery_requeues_dead_worker_job`,
  `test_restart_resumes_completed_chapters`, `test_cancel_queued_job`) and
  the `test_e2e_*` suites.

### Open items (need user action or a later phase)

1. **P0.4 CI enforcement missing.** `python scripts/gen_ts_types.py --check`
   is not in `.github/workflows/ci.yml` — the local change could not be pushed
   because the GitHub OAuth token lacks `workflow` scope. Needs a PAT with
   `workflow` scope or a manual edit in the GitHub UI. Until then, drift
   between contracts and `api.generated.ts` will not fail CI (verified in
   sync as of 2026-08-12).
2. **Branch protection** (P0.1 manual step) — set in the GitHub UI; cannot be
   verified from the working copy.
3. **P0.5 chaos gate not automated.** "kill -9 at 20+ random points" exists as
   unit/integration coverage of lease, orphan-recovery, and terminal-guard
   logic — not as a scripted chaos test.
4. **EPUB test warning.** `UserWarning: Duplicate name: 'EPUB/cover.xhtml'`
   during EPUB tests — the generator writes a duplicate zip entry. Harmless
   but worth a look in a later EPUB pass.
