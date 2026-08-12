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

## 2026-08-12 (P1.0 session): test-infrastructure defects found while making
## the golden path honest

### Fixed this session

1. **`stub_pipeline` permanently froze stubs onto the pipeline singletons.**
   The fixture patched the `AudioUtils` class first, then the already-
   instantiated `jobs.pipeline._audio` singleton — so monkeypatch recorded
   the *already-stubbed* class value as the "original" and re-installed the
   stub as a permanent instance attribute at teardown. Same trap on the
   registry's Edge provider instance. Consequence: any real-audio test
   running after any stubbed test silently ran stubbed. Fixed: class-level
   patches only, plus defensive removal of shadowing instance attributes.
2. **Test env bound too late → suite ran against the developer's real
   `backend/cache/`.** `jobs.pipeline` instantiates
   `SynthesisCache(CACHE_FOLDER)` at import time; `test_jobs.py` imports
   `worker` at module top level; pytest imports test modules during
   collection — before the session env fixture ran. Result: the whole suite
   used `backend/cache/` (cwd-relative default), where stale 23-byte
   `b"ID3fake…"` chunks from the pre-P1.0 provider poisoned real synthesis.
   Fixed: env defaults now set at conftest import time; purged 8 sub-1KB
   poisoned entries from `backend/cache/`.

### Open (feeds P1.1)

3. **The synthesis cache is trusted blindly, forever.** `SynthesisCache.get`
   returns any non-empty file; nothing validates decodability or checksum on
   a cache hit, so one poisoned/stale entry silently becomes book audio (or,
   as observed, a hard merge failure). P1.1's media validation must cover
   cache hits, and a validation failure must invalidate the implicated cache
   entries before retrying — otherwise a poisoned entry retries forever.
4. **`_upload_chapter_audio` failure keeps the bad chapter in the current
   run's assembly — P0.2 spec error, confirmed by the author 2026-08-12.**
   `chapter_files` is appended before the upload/validation try/except
   (pipeline.py:320 vs :328); on failure the row is reset to pending for the
   *next* run, but the in-memory path still feeds *this* run's final MP3/M4B.
   The P0.2 spec prescribed exactly this ordering ("Call the upload after the
   per-chapter session.commit()"). Correct ordering, in P1.1 scope:
   synthesize → validate → upload → verify → only then append to the
   assembly list and mark done.
5. **Post-fix honest test baseline: 169 passed, 1 skipped** (74.6s,
   2026-08-12, after the teardown fix and cache purge). The previous "156
   passed" was measured under the broken fixture. 169 = 156 + 13 new P1.0
   tests — no previously-passing test broke once the stubs stopped leaking,
   so the old suite's *state-machine* coverage was sound; it was the audio
   layer that was never tested.

### Deployment exposure (user deciding; logged for the record)

- **Branch protection is now blocked on the billing lock** — required checks
  that cannot start would wall off `main` entirely. User holds off until CI
  produces a run with non-zero steps.
- **Vercel auto-deploys `main` to production on every push with no test
  gate.** Combined with CI never running, everything pushed since 2026-08-07
  reached production unverified. Pausing auto-deploy is the user's call; not
  a blocker for the remediation program.

## 2026-08-12 (P1.2 session)

- **Another P0.3 leftover: `k8s/base.yaml` still deployed `v1-api`**
  (Deployment + Service + HPA + an ingress `/v1` route pointing at it) — my
  own earlier sweep missed it because a `head -5` truncated the grep. Removed
  in P1.2 along with the Celery `pipeline-worker` Deployment/Service and the
  Redis-based KEDA ScaledObject.
- **Redis is now possibly vestigial.** After deleting the Celery fabric,
  the only code touching `REDIS_URL` is the optional ping in
  `healthcheck.py`. The compose `redis` service and `REDIS_URL` envs remain;
  P1.8 (health rewrite) should decide whether Redis stays or goes.

## 2026-08-12 (P1.3 session)

- **Two parallel character-casting systems exist.** The `/api/projects/:id/
  characters` CRUD (`CharacterVoiceMap`) feeds only the flag-gated
  multi-agent tagger; synthesis voices come from the separate Voice City
  casting path (`voice_direction.cast` at synthesize time, snapshotted per
  job). P1.3 proved audibility through the Voice City path. Unifying them
  (CharacterVoiceMap as the default cast source at job creation) is design
  debt for P2 — not fixed here per ground rule 5.
- **Pipeline-path lexicon emits `[pron:…]` tags into the synthesis text.**
  With PIPELINE_ENABLED=true and a plain provider, tags would be read
  aloud. The default path (P1.3) uses plain phonetic replacement instead;
  the tag consumer only exists in the flag-gated world. Logged, not fixed —
  the pipeline is flag-gated off.

## 2026-08-12 (P1.6 session)

- **EPUB-from-job now carries the SPOKEN text by design** (active revision
  source_text: preprocessed, lexicon-applied). A reader sees "NWIN" where
  the author wrote "Nguyen". That is the spec'd behavior (EPUB matches the
  audiobook), but a reader-facing "original text" EPUB variant may be wanted
  later — product call, logged.
- **Backend suite runtime is now ~8 minutes** (real-audio E2E across
  P1.0–P1.6). Fine locally; when Actions unlocks, CI wall-clock will be
  dominated by it. Splitting fast/slow markers is an easy later win.

## 2026-08-12 (P1.8 session)

- **Redis is now officially optional.** Readiness does not check it (nothing
  in the deployed runtime uses it since the Celery deletion); the legacy
  `healthcheck.py` script and the compose `redis` service remain only as
  unused conveniences. Dropping them is a user call.
- **`/api/health` retained for dashboard back-compat**; the real contract is
  now `/health/live` (liveness, dependency-free) + `/health/ready`
  (DB / migration stamp / storage round-trip / worker heartbeat age /
  provider availability; hard failures 503, soft signals degraded-200).

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
