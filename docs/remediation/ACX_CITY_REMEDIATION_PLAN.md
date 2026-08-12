# ACX City — Remediation & Reliability Program

**Repository:** `github.com/Mangu-Platforms/acx-city`
**Document status:** Execution-ready plan. No code changes proposed here — this is the contract that governs the code changes.
**Verification basis:** Every claim below was checked against a fresh clone of `main`. Builds and test suites were executed, not inferred. Evidence is cited as `path:line` or as a reproducible command.
**Date of verification:** 7 August 2026

---

## 0. Objective

> **Every feature visible to a user must execute through one production architecture, survive realistic failures, resume safely, produce a valid result, and have an automated end-to-end test proving it.**

That objective is correct and is retained verbatim from the source plan. This document does three things to it:

1. **Corrects** the factual claims that do not match the repository (six material corrections, §2).
2. **Adds** the defects the source plan did not find — including the single most important fact about this repository (§1).
3. **Converts** every exit gate from a prose assertion into a machine-checkable command, so "done" is not a matter of opinion.

**Scope note:** This program is about *capability and reliability* — does the tool work, does it survive failure, does it produce a valid audiobook. It is deliberately not a security program. Authentication and tenancy appear only where they are a functional blocker to collapsing the API surface (§4.3), not as an audit workstream.

---

## 1. The finding that reorders everything: `main` does not build

The source plan proposes a release-gate discipline built on CI. That discipline cannot be applied yet, because **all three CI jobs are currently red on `main`.** This was established by execution, not inspection.

| CI job | Command | Result | Evidence |
|---|---|---|---|
| `backend` | `pytest -q` | **FAIL** — 7 failed, 119 passed, 1 skipped | 5 real defects in `services/epub_generator.py`; 2 further failures env-suspect (see below) |
| `frontend` | `npm run build` (`tsc && vite build`) | **FAIL** — 2 TypeScript errors | `frontend/src/App.tsx:131`, `frontend/src/App.tsx:170` |
| `dashboard` | `next build` | **FAIL** — webpack error, build aborted | `dashboard/app/dashboard/pipeline/page.tsx:1` |

Reproduce:

```bash
git clone --depth 1 https://github.com/Mangu-Platforms/acx-city.git && cd acx-city
(cd backend   && pip install -r requirements.txt && JWT_SECRET=x pytest -q)
(cd frontend  && npm ci && npm run build)
(cd dashboard && npm install && npx next build)
```

**Detail — frontend (`npm run build` runs `tsc` first, so these abort the build):**

```
src/App.tsx(131,88): error TS2339: Property 'provider_voice_id' does not exist on type 'StockVoice'.
src/App.tsx(170,25): error TS2322: Type '"characters" | "lexicon" | "production"'
                     is not assignable to type 'Page'.
```

**Detail — dashboard.** One file, `dashboard/app/dashboard/pipeline/page.tsx`, carries **five independent defects**:

1. **No `'use client'` directive** while using `useState`/`useEffect`/`useCallback`. Every sibling page (`dashboard/page.tsx`, `health/page.tsx`, `jobs/page.tsx`) has it. This alone fails `next build`.
2. **Wrong import path** — `from '../../lib/api'` resolves to `app/lib/api`, which does not exist. Correct is `../../../lib/api`.
3. **Missing dependency** — imports `lucide-react`, which is absent from `dashboard/package.json`.
4. `page.tsx:37` — implicit `any` parameter.
5. `page.tsx:41` — operating on a value of type `unknown`.

**Detail — backend.** The 5 EPUB failures are genuine defects in `services/epub_generator.py` against its own pinned `ebooklib==0.18`:

```
tests/test_epub_generator.py:16  AttributeError: 'EpubBook' object has no attribute 'chapters'
tests/test_epub_generator.py:40  TypeError: 'EpubHtml' object is not iterable
```

Root cause at `backend/services/epub_generator.py:92` — `len(self.book.chapters)`. `EpubBook` has no `chapters` attribute in ebooklib 0.18.

The 2 remaining failures (`TestGPUSynthesis::test_synthesis_router_default`, `::test_normalize_loudness`) fail with `AttributeError: module 'lib' has no attribute 'X509_V_FLAG_NOTIFY_POLICY'` — a `pyOpenSSL`/`cryptography` version conflict in the verification sandbox. **These are probably environment artifacts, not repository defects.** Confirm against GitHub Actions before counting them.

### Consequence for the plan

**A new phase P0.0 is inserted before everything else: get `main` green.** Until CI passes, "the build must fail before merge" is not a gate — it is the ambient condition, and every subsequent gate in this program is unenforceable. This is roughly a day of work and it unblocks the entire program.

There is also a governance implication. A repository whose three build jobs are all red has been merging without reading CI. Fixing the code without fixing that habit will simply reproduce the state. See §9.

---

## 2. Corrections to the source plan

The source plan is directionally excellent and its architecture judgment is correct. These are the places where it asserts something the repository does not support. Each correction matters because it redirects effort.

### 2.1 — Process supervision is already correct (source §20 is wrong)

The source plan states:

> "The combined deployment currently starts the worker in the background and then launches Gunicorn. If the worker dies while Gunicorn remains alive, the service can appear healthy while no audiobooks are processing."

**This is not what the code does.** `backend/start_combined.sh`:

```bash
python worker.py &
gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 2 --threads 4 --timeout 3600 wsgi:app &
wait -n
exit $?
```

`wait -n` returns as soon as *either* child exits; the script then exits and the platform restarts the whole service. The supervision requirement in the source plan is already satisfied.

**The real gap is different, and the fix is not a supervisor rewrite:**

- **A wedged worker is invisible.** `wait -n` catches a worker that *dies*. It cannot catch a worker that is alive but stuck — blocked on a provider socket, spinning, or deadlocked. That is the more common production failure.
- **`/api/health` never looks at the worker.** `backend/app.py:543` checks only `SELECT 1` and provider descriptors.
- **There is no worker heartbeat anywhere in Postgres.** No table, no column, no row. Nothing outside the worker process knows a worker exists.
- Minor: the script does not kill the surviving sibling before exiting. Largely moot because the container is being torn down, but worth one line.

**Redirected work:** build a `worker_heartbeats` table and a real readiness endpoint (§5.7). Do not rewrite `start_combined.sh` beyond adding sibling cleanup.

### 2.2 — The QC gate already exists (source §16 is half-wrong)

The source plan says QC is "metadata displayed after the fact, not an actual gate." The repository already has a real gate:

- `QCPolicy` enum — `off` / `warn` / `block` — at `backend/db/models.py`.
- `JobStatus.needs_review` — an explicit terminal-but-recoverable state.
- `jobs/pipeline.py` computes `gate_passed` and `worker.py` routes to `q.hold_for_review()`.
- Human approve/reject endpoints at `app.py:433` and `app.py:446`.
- Per-org policy override via `Organization.qc_policy`, resolved by `resolve_qc_policy()`.
- Covered by `tests/test_qc_gate.py`.

**The real gaps are narrower and more specific:**

- QC runs *after* chapter assembly and normalization, with **no media validation before it** — a truncated or undecodable artifact reaches QC as though it were audio.
- The gate is evaluated **once, at end of job**. A chapter that fails QC still gets written into `chapter_files` and assembled into the book; the job is held afterward. The bad chapter is inside the artifact.
- QC policy is not versioned, so a book built under an older policy cannot be interpreted later.

**Redirected work:** insert media validation *before* QC and make the per-chapter gate block advancement, rather than building a QC system that already exists.

### 2.3 — Usage/cost ledger already exists (source plan omits it)

`UsageEvent` (`db/models.py`) records provider, characters, `cost_usd`, and a `YYYY-MM` period bucket, with `ix_usage_org_period` for quota checks. `billing.record_usage()` is called from the synthesis loop for every paid chunk. `Organization.monthly_char_quota` exists. `tests/test_billing.py` and `tests/test_limits_api.py` cover it.

This is a genuine asset the source plan does not credit, and it changes the argument for idempotency: **duplicate synthesis is already measurable in dollars.** Use it as the metric for §5.4.

### 2.4 — Celery: compose is probably fine, k8s is definitively broken

The source plan reports a "Celery target mismatch" in both. Precisely:

- `celery_app` **does exist**, at `backend/pipeline/__init__.py:22`.
- `docker-compose.yml:88` uses `-A pipeline.celery_app`. Celery's `find_app` falls back to attribute lookup on the `pipeline` package, so this **likely resolves correctly**.
- `k8s/base.yaml:256` uses `-A pipeline_app`. No such module exists. **Definitively broken.**
- Open question to verify: `pipeline/tasks.py` uses `@shared_task` and is not imported by `pipeline/__init__.py`. Task registration may depend on autodiscovery that is not configured. Verify before relying on any Celery claim.

The malformed database URL claim is **confirmed** — `docker-compose.yml:106` contains a Unicode ellipsis and a truncated value:

```yaml
DATABASE_URL: postgresql+psycopg://audiobook:${POSTGRES_PASSWORD:-audio…book
```

### 2.5 — The autonomous workflow cannot merge (source §30 overstates, but the conclusion holds)

`.github/workflows/main.yml` pushes to a branch and opens a PR — it does **not** push to `main`, and the resulting PR is still subject to `pull_request` CI. The source plan's framing ("bypass quality gates") is too strong.

The actual problems are still disqualifying:

- **Unpinned tooling:** `pip install aider-chat radon bandit pytest coverage` — no version constraints, on a daily schedule.
- **Four blind sequential rewrites of the entire codebase, every day at 02:00**, each with `--yes --auto-commits`.
- **Self-validation is a no-op:** `pytest ... || echo "Tests failed, but proceeding to PR for human review."`
- `permissions: contents: write`.
- Burns `OPENAI_API_KEY` budget nightly with no cost ceiling.

**Conclusion unchanged: disable it.** But state the reason accurately — it generates unreviewable daily churn against a codebase that does not currently build, not that it bypasses CI.

### 2.6 — The capability matrix in the source plan is a guess

The source matrix marks MP3 export, M4B export, upload and generate as "Production." Given §1, nothing is production. Several other cells are unsupported by the code. §3 replaces it with an evidence-based matrix.

---

## 3. Evidence-based capability matrix

This replaces the source plan's matrix. It is the artifact that should land at `docs/CAPABILITY_MATRIX.md` and become the release gate.

**Column definitions — these must be mechanical, not editorial:**

- **UI** — a user-reachable control exists in `frontend/`.
- **API** — an endpoint exists on the canonical Flask `/api` surface *and* returns a valid response for a valid request.
- **Exec** — the code path that performs the work runs in the deployed production topology (Flask API + `worker.py`). Celery/FastAPI paths score **No**, because neither is deployed.
- **Durable** — the result survives a container replacement (object storage or Postgres, not local disk).
- **Resume** — a worker kill mid-operation resumes without duplicate paid synthesis.
- **E2E** — an automated test exercises UI/API → execution → persistence → output.
- **Ship** — all of the above are Yes.

| Capability | UI | API | Exec | Durable | Resume | E2E | Ship | Evidence |
|---|---|---|---|---|---|---|---|---|
| Signup / login | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:193-235`; `tests/test_api.py` |
| Upload manuscript | Yes | Yes | Yes | Yes | n/a | Partial | **No** ¹ | `app.py:252` |
| Generate audiobook (single voice) | Yes | Yes | Yes | Partial | Partial | Partial | **No** | `jobs/pipeline.py`; chapter audio local-disk only (§4.1) |
| Chapter progress / resume | — | Yes | Yes | Partial | Partial | Yes | **No** | `ChapterResult` persists state but not the artifact (§4.1) |
| MP3 export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `storage.put_file` |
| M4B export | Yes | Yes | Yes | Yes | Partial | Partial | **No** | `jobs/pipeline.py`; `_audio.export_m4b` |
| Job cancel | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:409`; `tests/test_jobs.py` |
| QC gate + human review | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:433,446`; `tests/test_qc_gate.py` |
| Usage / quota ledger | Partial | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `UsageEvent`; `tests/test_billing.py` |
| Signed-URL download | Yes | Yes | Yes | Yes | n/a | Yes | **No** ¹ | `app.py:460`; `tests/test_download.py` |
| Character detection | Yes | `/v1` | **No** | Partial | No | **No** | **No** | `v1_api.py:275`; Celery not deployed |
| Character voice assignment | Yes | `/v1` | **No** | Yes | No | **No** | **No** | `v1_api.py:302`; `CharacterVoiceMap` |
| Pronunciation lexicon | Yes | `/v1` | **No** | Yes | No | **No** | **No** | `v1_api.py:342-397` |
| Multi-agent pipeline | Partial | `/v1` | Flag-gated | Partial | No | **No** | **No** | `PIPELINE_ENABLED` default `false` |
| Voice preview | Yes | **Broken** | **No** | No | No | **No** | **No** | 3 independent defects (§4.5) |
| Chapter streaming | Partial | **Broken** | **No** | No | No | **No** | **No** | `AttributeError` on request (§4.6) |
| Waveform | Partial | **Broken** | **No** | No | No | **No** | **No** | Wrong column; returns `peaks: []` (§4.7) |
| Single-chapter rerender | Partial | **Broken** | **No** | No | No | **No** | **No** | Sends whole book as chapter text (§4.8) |
| Voice cloning | Yes | **501** | **No** | No | No | **No** | **No** | `v1_api.py:567` raises `501` (§4.9) |
| EPUB export (from job) | Partial | **Broken** | **No** | No | No | **No** | **No** | 3 wrong ORM attrs + broken generator (§4.4) |
| EPUB export (client-supplied) | Partial | Partial | Yes | Yes | n/a | **Failing** | **No** | `app.py:618`; 5 unit tests red |

¹ These capabilities are functionally sound. They score **No** only because the shipping product does not build (§1). They flip to Yes on completion of P0.0 plus an E2E test.

**Headline number: 0 of 22 capabilities are shippable today.** Ten are one green build away. Eleven are structurally broken. That is the honest baseline, and it is a far better starting position than it sounds — the core is genuinely sound, and the broken eleven are almost entirely confined to one untested surface.

---

## 4. Verified defect register

Every entry below was confirmed by reading the code at the cited location. Severity: **S1** = silently produces a wrong result or loses money; **S2** = feature is dead on arrival; **S3** = correctness/robustness hazard under load or failure.

### 4.1 — S1: Chapter audio and synthesis cache never leave local disk

`jobs/pipeline.py` writes every chapter to `os.path.join(OUTPUT_FOLDER, job.id, f"chapter_{i:03d}.mp3")`. `SynthesisCache` writes to `CACHE_FOLDER`. **Only the final merged MP3/M4B is uploaded to object storage.** `ChapterResult` has **no** storage-key, checksum, or size column — the durable record knows a chapter is `done` but not where it is or whether it is intact.

Resume logic:

```python
if row.status == ChapterStatus.done:
    path = os.path.join(task_dir, f"chapter_{i:03d}.mp3")
    if os.path.exists(path):
        chapter_files.append(path); chapter_titles.append(chapter["title"]); continue
```

If the file is gone, it falls through and re-synthesizes. So the book is not silently truncated — **but every chapter and every cache entry is re-synthesized at full provider cost.** On the documented Railway topology this is survivable only because a volume is mounted to the single combined service. `start_combined.sh` says so explicitly: *"Railway mounts a volume to exactly one service... So on Railway both processes run in this single combined service."*

This is the single largest obstacle to the source plan's §5–§7 goals. Crash-safety, idempotency, rerender and streaming **all** require a durable per-chapter artifact. It should be the first structural change after P0.0.

**Required:** chapter audio uploaded to storage on completion; `ChapterResult` gains `audio_key`, `audio_sha256`, `audio_bytes`, `duration_s` (exists), `content_type`; resume checks `storage.exists(audio_key)` and verifies the checksum, not `os.path.exists`.

### 4.2 — S1: Orphan recovery and cooperative cancel collide, and can produce two workers on one job

The most severe concurrency defect in the repository. Sequence:

1. Worker A claims job J. `locked_at` stamped.
2. Chapter processing exceeds `DEFAULT_LEASE_SECONDS` (900s) — entirely normal for a long chapter with chunk retries, since `should_continue()` is only called **between chapters** (`jobs/pipeline.py`, top of the chapter loop).
3. The orphan sweeper (`recover_orphans`, every 60s) sees `locked_at < cutoff`, sets `status=queued`, `locked_by=None`.
4. **Worker B claims J and starts synthesizing it — into the same `task_dir`.**
5. Worker A's next `should_continue()` calls `heartbeat()`, which returns `False` because `job.locked_by != worker_id`.
6. `run_job` raises `JobCanceled`. `worker.py` then executes:

```python
except JobCanceled:
    job.status = JobStatus.canceled
    job.locked_by = None
    job.locked_at = None
```

**Worker A unconditionally marks the job `canceled` — clobbering the requeued/running state that Worker B is operating under.** The user sees a cancelled job that nobody cancelled, while a second worker is still burning provider spend on it.

Three distinct bugs in one path:

- **(a)** Lease renewal is coupled to chapter progress, so lease expiry is a function of chapter length, not worker health.
- **(b)** `JobCanceled` conflates *user cancelled* with *lease lost*. These require opposite handling.
- **(c)** Cancellation writes are unconditional rather than guarded on still owning the lock.

**Required:** distinct exceptions (`JobCanceled` vs `LeaseLost`); on `LeaseLost` the worker abandons silently and writes nothing; all terminal transitions guarded by `WHERE locked_by = :worker_id`; heartbeat on a timer independent of pipeline progress (§5.2).

### 4.3 — S3: The heartbeat shares the pipeline's session and calls `session.refresh()`

`worker.py`:

```python
def should_continue() -> bool:
    # Refresh lock/cancel state on its own connection.
    return q.heartbeat(session, job, worker_id)
```

The comment says "its own connection." It is the **same** `session` the pipeline is mutating. `queue.heartbeat()` opens with `session.refresh(job)`, which expires the instance and reloads it — discarding any un-flushed in-memory changes to `job`, and reading within the same transaction rather than seeing other workers' committed state.

In practice the loop commits before each `should_continue()`, so damage is limited today. It is a latent trap that will fire the moment anyone adds an un-flushed mutation, and it makes the heartbeat unable to observe external changes. A timer-based heartbeat (§5.2) must use its **own** session and its own connection.

### 4.4 — S2: EPUB export is broken at two layers

**Layer 1 — the route.** `app.py:662` `export_job_as_epub` uses three attributes that do not exist:

| Code | Reality |
|---|---|
| `job.chapter_results` | relationship is `Job.chapters` |
| `result.chapter_title` | column is `ChapterResult.title` |
| `result.text_content` | **no such column exists anywhere** |

Wrapped in `except Exception as e: return jsonify({"error": str(e)}), 500` — so it returns a 500 carrying an `AttributeError` string.

**Layer 2 — the generator.** `services/epub_generator.py:92` calls `len(self.book.chapters)`; `EpubBook` has no `chapters` attribute in the pinned `ebooklib==0.18`. **Five unit tests fail.**

**Layer 3 — the design.** This cannot be fixed by renaming attributes. `ChapterResult` stores no text. The manuscript lives in `Project.source_text` and is re-split at synthesis time by `TextProcessor.split_by_chapters()`. To export EPUB from a job, the **chapter text as synthesized** must be persisted — which is the same requirement as reproducible rerender (§5.5). Fix the data model once and both features become possible.

### 4.5 — S2: Voice preview — three independent failures on the same request

`services/voice_catalog_endpoints.py:241` and `:322` call `VoicePreviewService`, which is written entirely `async` against interfaces that do not exist:

1. **`preview_voice` is `async def`.** Calling it returns a coroutine; it does not execute and does not raise. The surrounding `try/except` therefore catches nothing. The code then does:

```python
import asyncio
if asyncio.iscoroutine(result):
    result = asyncio.get_event_loop().run_until_complete(result)
```

Under Gunicorn's `--threads 4`, this runs on a non-main thread with no event loop → `RuntimeError: There is no current event loop`.

2. **Storage methods do not exist.** `voice_preview.py:186-187` calls `self._storage.upload(...)` and `self._storage.get_url(...)`. `StorageBackend` (`storage/base.py`) provides `put_bytes`, `put_file`, `get_bytes`, `exists`, `delete`, `signed_url`. No `upload`. No `get_url`.

3. **Provider interface does not exist.** `voice_preview.py:184` does `await tts.synthesize(...)`. Real providers implement `synthesize()` **synchronously**, returning `bytes`. Awaiting `bytes` is a `TypeError`.

The in-repo comment — *"The preview service is async in spirit but the existing codebase uses sync Flask"* — is the diagnosis. The source plan's instruction is correct and should be followed literally: **do not build a third adapter to reconcile two designs. Delete the async design and write preview against the real synchronous abstractions.**

### 4.6 — S2: Chapter streaming fails on every request, twice

`services/streaming.py:234`:

```python
if job.status != JobStatus.completed:
```

**`JobStatus` has no member `completed`.** The enum is `queued | running | succeeded | needs_review | failed | canceled`. This raises `AttributeError` on the enum class — a 500 on every call, not a wrong comparison.

Second, independent defect: `app.py:65` calls `create_streaming_blueprint()` **with no arguments**, so `AudioStreamer(registry=None)`. `/api/stream/preview` therefore raises `RuntimeError("ProviderRegistry not configured on AudioStreamer")`.

Third, which the source plan missed: even with a registry injected, `streaming.py:170` calls `self._registry.first_available()`. **`ProviderRegistry` exposes `get`, `default`, `describe_all` — there is no `first_available`.**

Fourth: the streamer resolves audio by rebuilding a local path (`OUTPUT_FOLDER/<job>/chapter_NNN.mp3`) — exactly the independent-path-inference the source plan forbids, and dependent on §4.1.

### 4.7 — S2: Waveform endpoint returns a placeholder and uses a non-existent column

`v1_api.py:520` reads `chapter.duration_seconds`; the column is `ChapterResult.duration_s` → `AttributeError`. And the body is explicitly a stub: `"peaks": []`, with the comment *"Waveform data would be pre-computed and stored."*

### 4.8 — S2: Rerender sends the entire book as one chapter

`v1_api.py:484`:

```python
task = process_chapter.delay(
    job_id=job.id,
    chapter_number=chapter.index,
    chapter_text=project.source_text,   # Simplified; in production, extract just this chapter
    chapter_title=chapter.title or f"Chapter {chapter.index}",
)
```

Two failures. The whole manuscript is passed as a single chapter's text. And `.delay()` requires a Celery broker — **Redis and the Celery worker are not part of the deployed Railway topology.** The call cannot dispatch in production.

### 4.9 — S2: Voice cloning is a 501 behind a working UI

`v1_api.py:567`:

```python
@app.post("/v1/voices/clone")
async def create_voice_clone(organization_id: str = Query(...)):
    """TODO: Implement multipart upload, Fish Speech S2 embedding computation..."""
    raise HTTPException(501, "Voice cloning not yet implemented — Phase 10")
```

`frontend/src/components/voxengine/VoiceCloneWorkbench.tsx:49` posts `FormData` to it. The `VoiceClone` model, the `voice_clones` table, and the UI all exist. The feature does not. This is the canonical case for the source plan's §12: **finish it or hide it behind a flag.**

### 4.10 — S2: The `/v1` surface has no identity

No `/v1` route has an auth dependency. Org scoping is done by **client-supplied query parameter**:

```python
async def list_voice_clones(organization_id: str = Query(...)):
```

Flagged here not as a security finding but as a **functional blocker**: the merge into `/api` (§5.1) cannot be a route-copy exercise, because `/api` derives the org from `current_identity()` and `/v1` has no identity to derive from. Every migrated handler needs its ownership argument replaced by the authenticated identity. Budget for that.

### 4.11 — S3: Twelve `/v1` call sites in shipping UI code

| File | Calls |
|---|---|
| `frontend/src/components/voxengine/LexiconEditor.tsx` | 3 (`:29`, `:43`, `:55`) |
| `frontend/src/components/voxengine/CharacterPanel.tsx` | 3 (`:43`, `:57`, `:68`) |
| `frontend/src/components/voxengine/MultiTrackStudio.tsx` | 2 (`:56`, `:101`) |
| `frontend/src/components/voxengine/VoiceCloneWorkbench.tsx` | 2 (`:30`, `:49`) |
| `frontend/src/components/voxengine/VoiceCatalog.tsx` | 2 (`:254`, `:304`) |
| `dashboard/app/dashboard/pipeline/page.tsx` | 1 (`:49`) |

All use the axios client whose `baseURL` is `/api` (`frontend/src/services/api.ts:20`), so `/v1/projects/...` resolves to **`/api/v1/projects/...`** — a path that exists on neither service. These are not "calls to the sidecar." They are calls to nothing.

### 4.12 — S3: The dashboard client has no `.get()`

`dashboard/lib/api.ts` exports an object of named operations (`login`, `me`, `health`, `jobs`, `job`, `cancelJob`, `approveJob`, `rejectJob`, `deleteJob`, `usage`, `cacheStats`). The pipeline page calls `api.get('/api/jobs')` and reads `res.data`. Neither the method nor the `.data` envelope exists — `req<T>()` returns the parsed body directly. Confirmed by `tsc` (§1).

### 4.13 — S3: Agent 2 and Agent 4 fallbacks assign the agent to the result variable

The source plan's most specific claim, **confirmed** — `backend/pipeline/tasks.py`:

```python
result2 = agent2.timed_run({"chapters": chapters}, context)
if not result2.success:
    _update_trace(trace_id, agent2_ms=result2.duration_ms, status="failed", error=result2.error)
    result2 = agent2          # line 138  ← agent instance, not AgentResult
...
_update_trace(trace_id, agent2_ms=result2.duration_ms, agent2_cost_usd=result2.cost_usd, ...)
chapters = result2.data.get("chapters", chapters)
```

Identical at line 170 for `result4 = agent4`. `result2.duration_ms`, `.cost_usd`, `.data` are then read off the agent object → `AttributeError`. **Graceful degradation converted into a hard crash.** Also note `total_cost = result2.cost_usd + ...` at the end compounds it.

The synchronous path `pipeline/integration.py` does **not** have this bug — but it has a related one: it checks `r1.success` and then never checks `r2`–`r5`, relying on a broad `except Exception` to fall back to plain preprocessing. So a partial agent failure silently degrades to unprocessed text with no signal to the user.

### 4.14 — S3: Voice City optimization jobs can starve

`worker.py` main loop:

```python
did_work = process_one(worker_id)
if not did_work:
    did_work = process_voice_city_one(worker_id)
```

Voice City optimization jobs are only claimed when **no** audiobook job is available. Under sustained audiobook load they never run. Two independent queues sharing one loop with strict priority. Needs either separate worker roles or fair interleaving.

### 4.15 — S3: Deployment manifests that have never run

- `docker-compose.yml:106` — malformed `DATABASE_URL` (Unicode ellipsis, truncated).
- `k8s/base.yaml:256` — `celery -A pipeline_app`; no such module.
- `k8s/base.yaml:291` — a `v1-api` Deployment for a service that is not part of the production topology.

None of these is exercised by CI. They are documentation that asserts something false.

### 4.16 — S1 (process): zero test coverage on the entire broken surface

```
tests referencing v1_api ........... 0
tests referencing pipeline.tasks ... 0
tests referencing streaming ........ 0
tests referencing voice_preview .... 0
```

Every S1/S2 defect in §4.4–§4.13 lives in a module no test imports. This is not a coincidence — it is the mechanism. The 127 existing tests cover the *old* surface well (jobs, queue, ownership, billing, storage, QC gate, retention, rate limiting, auth), which is precisely why the old surface works and the new one does not.

**This single metric is the most predictive number in the repository, and it belongs on the dashboard: `untested_modules_reachable_from_ui`.**

---

## 5. Target architecture and required designs

The source plan's target architecture is **correct and is adopted unchanged**:

```
          React Production UI                    Vercel Dashboard
                  │                                     │
                  └──────────► HTTPS /api/* ◄───────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  Flask Backend API  │   auth · projects · jobs · voices
                        │   (sole app-facing  │   characters · lexicon · previews
                        │      boundary)      │   rerenders · exports
                        └──────────┬──────────┘
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              PostgreSQL     Object Storage   Provider Registry
                    │
                    │ durable queue (FOR UPDATE SKIP LOCKED)
                    ▼
            ┌───────────────────┐
            │ Production Worker │  ingest → normalize → attribution →
            │   (worker.py)     │  voice assignment → pronunciation →
            └─────────┬─────────┘  prosody → TTS → validate → QC →
                      ▼            assemble → export
              finished audiobook
```

**Invariants:** one public HTTP API. One queue. No Redis on the main product path. No UI bypassing the canonical backend. No worker implementation bypassing the durable job system.

### 5.1 — Collapse the API surface

Extract business logic from FastAPI handlers into plain service modules; make Flask blueprints thin adapters.

```
backend/services/
    character_service.py      ← from v1_api.py:275-341
    lexicon_service.py        ← from v1_api.py:342-411
    voice_service.py          ← from v1_api.py:412-483
    preview_service.py        ← rewrite; do not port voice_preview.py
    rerender_service.py       ← redesign; do not port v1_api.py:484
    pipeline_service.py       ← from v1_api.py:105-274
```

Target routes:

```
/api/projects/:id                       /api/voices
/api/projects/:id/characters            /api/voices/:id/preview
/api/projects/:id/lexicon               /api/voice-clones
/api/jobs/:id                           /api/voice-clones/:id
/api/jobs/:id/pipeline                  /api/exports/...
/api/jobs/:id/chapters/:chapter
/api/jobs/:id/chapters/:chapter/rerender
```

Pydantic request/response models must not appear in service signatures. Every migrated handler replaces its `organization_id` argument with `current_identity()` (§4.10).

**Exit gate (all must pass):**

```bash
rg -n '/v1' frontend/src dashboard --type ts --type tsx   # → 0 matches
rg -n 'fastapi|uvicorn' backend --type py                  # → 0 matches
test ! -f backend/v1_api.py
```

### 5.2 — Lease and heartbeat

Add to `jobs`: `worker_id`, `claimed_at`, `heartbeat_at`, `lease_expires_at`, `last_error_code`. Keep `attempts`, `max_attempts`.

```
worker claims job
     │
     ├── heartbeat thread ──── every 30s, OWN session, OWN connection:
     │                           UPDATE jobs SET heartbeat_at=now(),
     │                             lease_expires_at=now()+interval '5 min'
     │                           WHERE id=:job AND worker_id=:me
     │                         0 rows updated → signal LeaseLost, stop
     │
     └── pipeline thread ───── processes the audiobook, checks a flag
```

A chapter may take five seconds or fifty minutes without the worker appearing dead. Orphan recovery keys on `lease_expires_at < now()`, not on `locked_at + constant`.

**Cancel vs. lease-loss must be separate exceptions** (§4.2). Every terminal transition is guarded:

```sql
UPDATE jobs SET status = :terminal WHERE id = :job AND worker_id = :me
```

Zero rows updated means the job is no longer ours — write nothing, log, move on.

**Exit gate:** `kill -9` the worker at 20 randomly-chosen points across a job; 20/20 resume; zero jobs end in `canceled` without a user cancel request.

### 5.3 — Stage checkpoints

Model the job as a state machine, not one operation:

```
INGESTED → SPLIT → NORMALIZED → CHARACTERS_RESOLVED → VOICES_ASSIGNED
→ LEXICON_APPLIED → PROSODY_READY → SYNTHESIZED → VALIDATED → QC_PASSED
→ ASSEMBLED → EXPORTED
```

Note the addition of **`VALIDATED`** between `SYNTHESIZED` and `QC_PASSED` — media validation is a distinct stage from QC (§2.2, §5.6).

New table `job_stages`:

| column | purpose |
|---|---|
| `job_id`, `stage`, `attempt` | identity — **`UNIQUE(job_id, stage, attempt)`** |
| `status` | pending / running / succeeded / failed / skipped |
| `input_hash`, `output_hash` | resume and reproducibility |
| `started_at`, `finished_at` | timeline |
| `implementation_version` | so old runs stay interpretable |
| `error_code`, `error_message` | actionable failure |
| `cost_usd`, `duration_ms` | measurement |

The existing `PipelineTrace` moves in this direction but has only a non-unique index (`ix_pipeline_traces_job_chapter`), so retries append duplicate rows with no way to identify the authoritative one. **Add the uniqueness constraint as part of this work.**

### 5.4 — Idempotent synthesis

Deterministic identity for every synthesis unit:

```
synthesis_id = sha256(
    normalized_text ‖ provider ‖ provider_voice_id ‖ engine ‖
    speed ‖ pitch ‖ volume ‖ style ‖ prosody_plan_hash ‖
    lexicon_revision ‖ provider_model_version
)
```

`jobs/pipeline.py` already computes a cache discriminator with most of these inputs. **Two changes are required:** the identity must be **persisted in Postgres**, not just used as a local filename; and `provider_model_version` and `lexicon_revision` must be included so a provider model change or pronunciation edit correctly invalidates.

Ordering — non-negotiable:

```
1. look up synthesis_id in the DB cache
2. if hit → verify the object still exists and its checksum matches → reuse
3. synthesize
4. write audio to object storage
5. validate the artifact (§5.6)
6. record checksum + size + duration
7. commit ChapterResult in the same transaction as the cache row
```

A worker that dies between 4 and 7 must, on retry, **discover the finished artifact rather than paying for it again.** Measure this in dollars via the existing `UsageEvent` ledger (§2.3).

### 5.5 — Chapter revisions and rerender

```
ChapterResult (job_id, index)
   └── ChapterRevision (revision 1, 2, 3…)
          audio_key · audio_sha256 · duration_s · synthesis_id
          voice_snapshot_id · lexicon_revision · prosody_hash
          source_text          ← also fixes EPUB export (§4.4)
          qc_result · qc_policy_version · status · created_at
```

`ChapterResult` points at `active_revision_id`. Storing `source_text` per revision resolves §4.4 and makes rerender reproducible in one change.

```
change detected (voice │ pronunciation │ character │ prosody │ text)
      → compute affected chapter set
      → create revision N+1 for those chapters only
      → synthesize → validate → QC
      → on pass: flip active_revision_id
      → rebuild assembly from active revisions
```

The previous revision stays live until the replacement passes QC — that is the transactional safety property. **One pronunciation change must never re-render a whole book.**

**Exit gate:** change one character's pronunciation in a 20-chapter book; exactly the chapters containing that word re-synthesize; `synthesized_chunks` for unaffected chapters is unchanged; the previous audio remains playable throughout.

### 5.6 — Media validation before QC

A 200 from a TTS provider is not proof of usable audio. Between synthesis and QC:

```
exists → size > 0 → ffprobe decodes → expected codec/container
→ duration > 0 → duration plausible for character count (±tolerance)
→ channels valid → sample rate valid → not truncated
```

Failure ⇒ artifact rejected, synthesis retried, **chapter state does not advance**. Only validated audio reaches QC. Only QC-passed audio reaches assembly. This is the fix for §2.2 — the gate exists; what is missing is the step before it and per-chapter enforcement.

Version the QC profile (`qc_policy_version` on the revision) so books built under an older policy remain interpretable.

### 5.7 — Liveness, readiness, and worker heartbeat

Split the single `/api/health` (`app.py:543`):

| Endpoint | Meaning | Checks |
|---|---|---|
| `/health/live` | the process is alive | nothing external; never fails on a dependency |
| `/health/ready` | the application can do work | DB connectivity · schema/migration compatibility · storage accessibility (round-trip a probe key) · **worker heartbeat age** · required provider initialization |

New table `worker_heartbeats(worker_id, role, started_at, heartbeat_at, jobs_claimed, version)`. The worker upserts every 30s. Readiness reports `worker: healthy | stale | absent` from the max `heartbeat_at`.

Provider outages produce **degraded**, not a crash. The Dockerfile `HEALTHCHECK` should point at `/health/live`; the platform's readiness probe at `/health/ready`.

Also add sibling cleanup to `start_combined.sh` (§2.1) — small, but correct:

```bash
python worker.py & WORKER_PID=$!
gunicorn ... & API_PID=$!
wait -n
kill "$WORKER_PID" "$API_PID" 2>/dev/null
exit 1
```

### 5.8 — One API contract, generated not guessed

```
backend/api/contracts/{jobs,projects,voices,pipeline,exports}.py
        │
        ▼  OpenAPI schema emitted in CI
        ▼
   generated TypeScript types  →  frontend + dashboard (both import the same package)
```

Models: `JobResponse`, `JobListResponse`, `ChapterResponse`, `ChapterRevisionResponse`, `PipelineStatusResponse`, `CharacterAssignmentResponse`, `VoiceResponse`, `VoicePreviewResponse`, `ExportResponse`.

Per-endpoint contract tests: request validation · response validation · not-found · invalid-state · retryable-failure · authorization.

**Exit gate:** a CI job regenerates types and fails on any diff. A backend response-shape change that breaks either UI fails CI **before** merge. This is what would have caught §4.12 and all twelve call sites in §4.11.

### 5.9 — One voice object

```
Voice: id · provider · provider_voice_id · display_name · language · locale
       gender/style metadata · clone_status · capabilities[]

capabilities ⊆ { synthesis, preview, cloning, style, ssml, speed, pitch }
```

The UI renders only controls the voice/provider actually supports. A preview failure returns a clean capability error; it does not crash a page. Previews are cached aggressively and keyed by `(voice, sample_text, provider_model_version)`.

Note the existing model duplication to resolve: `StockVoice` (`db/voxengine_models.py`) and `VoiceCityVoice`/`VoiceCityVoiceVersion` overlap by the repository's own admission — *"The bible's `stock_voices` concept is already served by VoiceCityVoice."* Two voice tables cannot both be canonical.

### 5.10 — Deterministic fake TTS provider

`FakeSpeechProvider` generating real, decodable, deterministic short audio locally, with configurable behaviours:

```
success · timeout · temporary_failure · permanent_failure
invalid_audio · truncated_audio · silent_audio
slow_response · rate_limited · fail_after_n_calls
```

This is the highest-leverage single item in the entire program. It makes every failure-injection test in §7 cheap, deterministic, offline, and free. Build it in P0.7, before the golden-path test, not after.

---

## 6. Program sequence

Ordering matters — later work depends on earlier invariants.

| # | Package | Exit gate (machine-checkable) |
|---|---|---|
| **P0.0** | **Get `main` green** | `pytest -q` · `npm run build` (frontend) · `next build` (dashboard) all exit 0 |
| **P0.1** | Freeze expansion; publish evidence-based capability matrix; disable `main.yml` | `docs/CAPABILITY_MATRIX.md` merged; `.github/workflows/main.yml` disabled; branch protection requires CI |
| **P0.2** | Durable chapter artifacts (§4.1) — storage keys + checksums on `ChapterResult` | Wipe `OUTPUT_FOLDER` mid-job; job resumes with **zero** re-synthesis of completed chapters |
| **P0.3** | One Flask `/api` surface (§5.1) | `rg '/v1' frontend/src dashboard` → 0; `rg 'fastapi' backend` → 0; `v1_api.py` deleted |
| **P0.4** | Contract layer + generated TS types (§5.8) | Type-regeneration job fails CI on diff; both UIs consume the generated package |
| **P0.5** | Heartbeat, lease, cancel/lease-loss separation (§5.2, §4.2, §4.3) | 25/25 random `kill -9` recoveries; 0 spurious `canceled`; 0 double-claims |
| **P0.6** | Stage checkpoints + idempotent synthesis (§5.3, §5.4) | Forced retry produces 0 duplicate `UsageEvent` rows and 0 duplicate provider calls |
| **P0.7** | `FakeSpeechProvider` (§5.10) | Full pipeline runs in CI offline, deterministically, in under 2 minutes |
| **P0.8** | Golden-path E2E in CI (§7 Layer C) | Green on every PR; artifact decodes; chapter count and order verified |
| **P1.1** | Media validation before QC; per-chapter gate (§5.6) | Corrupt/truncated/silent artifacts rejected; chapter state does not advance |
| **P1.2** | Multi-agent pipeline convergence — fix §4.13, run in `worker.py`, no Celery | Agent failure returns `success=false, fallback_used=true`; type never changes |
| **P1.3** | Character / voice / lexicon on `/api` (§5.9) | Assignments and lexicon demonstrably change the produced audio |
| **P1.4** | Preview + streaming rewrite (§4.5, §4.6) | Preview returns a signed URL; streaming honours Range; both under E2E |
| **P1.5** | Chapter revisions + rerender (§5.5) | One-word pronunciation change re-renders only affected chapters |
| **P1.6** | Export repair — EPUB, MP3, M4B, manifests (§4.4) | All export unit tests green; every export decodes; manifest reproducible |
| **P1.7** | Dashboard rebuild against the canonical client (§4.12) | Builds; observational only; job-detail shows the full stage timeline |
| **P1.8** | Liveness / readiness / worker heartbeat (§5.7) | Killing the worker flips `/health/ready` to `worker: stale` within 90s |
| **P2.1** | Voice cloning — finish or hide (§4.9) | Either a full lifecycle with validation, or the UI action is absent behind a flag |
| **P2.2** | Failure-injection suite (§7 Layer F) | All 16 scenarios automated and green |
| **P2.3** | Cancellation granularity (§8) | Cancel during a 50-minute chapter takes effect in < 30s |
| **P2.4** | Performance work on measured bottlenecks | Only against profiles from production data |
| **P3** | Reconsider Redis / Celery / K8s | Only if measurement proves the durable worker is the bottleneck |

---

## 7. Test architecture

**Layer A — unit.** Chapter splitting · normalization · character attribution parsing · lexicon application · synthesis-identity computation · voice capability resolution · QC rules · storage key generation · job state transitions · retry classification · **stage transition legality**.

**Layer B — integration** (real Postgres + fake storage + `FakeSpeechProvider`). Enqueue · claim · heartbeat · lease expiry · retry · cancel · orphan recovery · chapter persistence · revision creation · rerender · export.

**Layer C — golden audiobook.** A small fixture manuscript, end to end: upload → create job → process → chapters → validate → QC → assemble → export → download → **decode and verify the output**. Runs on every PR.

**Layer D — frontend E2E.** Login · upload · start job · observe progress · play a chapter · change a voice · rerender a chapter · download an export.

**Layer E — dashboard E2E.** Job appears · progress updates · failure visible · retry visible · worker health visible.

**Layer F — failure injection.** Each row is an automated test, not a QA instruction:

| Injected failure | Required behaviour |
|---|---|
| Worker dies before chapter starts | Another worker resumes; no duplicate synthesis |
| Worker dies during TTS | Retry; at most one billable call for that unit |
| Worker dies after TTS, before DB commit | Artifact discovered and reused, not regenerated |
| Worker dies after DB commit | Chapter never synthesized twice |
| **Lease expires during a long chapter** | Job is NOT marked canceled; exactly one worker continues (§4.2) |
| Database briefly unavailable | Retry without corruption |
| Storage write fails | Chapter remains incomplete; no partial artifact observable |
| Storage returns corrupt/truncated audio | Validation rejects it; chapter does not advance |
| Provider times out | Backoff and retry |
| Provider rate-limits | Backoff and retry |
| Provider permanently fails | Job enters an actionable failure state with an error code |
| FFmpeg crashes | Export fails cleanly; prior state intact |
| Disk full | Job stops without corruption |
| User cancels during synthesis | Stops at a safe checkpoint within 30s |
| User rerenders while worker active | No conflicting revisions |
| API restarts | Worker continues uninterrupted |
| Worker restarts | UI still shows correct state |

**Idempotency tests.** Run every expensive operation twice deliberately:

```
same job claimed twice        → one effective worker
same chapter synthesized twice → one final result, one UsageEvent
same rerender requested twice  → one revision
same export requested twice    → same or safely-duplicated immutable artifact
```

Enforce with database constraints where possible — `UNIQUE(job_id, stage, attempt)`, `UNIQUE(job_id, index, revision)`, `UNIQUE(synthesis_id)` — rather than application logic alone.

---

## 8. Cancellation

Currently checked only between chapters. Check at:

```
before chapter · before each provider call · after each provider call
· between synthesis chunks · before validation · before QC
· before assembly · before export
```

A 50-minute chapter must not have to finish before a cancel takes effect. **Target: cancellation observable in under 30 seconds at any point.** Cancellation is a robustness property, not a UI convenience — an uncancellable job is an unbounded spend.

---

## 9. Release gates

Quantitative. No feature is "Production" in the capability matrix until its row is all-Yes and these hold:

| Gate | Target |
|---|---|
| Backend suite | pass, 0 failures |
| Frontend build | pass |
| Dashboard build | pass |
| Contract/type regeneration | no diff |
| Golden-path runs | 50 consecutive successes |
| Worker-kill recovery | 25/25 recover |
| Duplicate synthesis after recovery | 0 |
| Spurious `canceled` from lease loss | 0 |
| Lost completed chapters | 0 |
| Corrupt final exports | 0 |
| UI/API contract failures | 0 |
| Schema migration | upgrade → downgrade → upgrade succeeds |
| Cancel/rerender concurrency cases | 100% deterministic |
| Real-provider smoke | repeated successful samples |
| `untested_modules_reachable_from_ui` | **0** |

That last metric is the one that would have prevented this entire situation (§4.16). Track it from day one.

**Process gates, which matter as much as the numeric ones:**

- Branch protection requires all three CI jobs. §1 proves this is not currently enforced.
- Incomplete features sit behind explicit feature flags and their UI controls are **absent**, not disabled-looking. `PIPELINE_ENABLED` is the correct existing pattern.
- No new capability merges without its row in `docs/CAPABILITY_MATRIX.md` and an automated test.

---

## 10. Explicitly out of scope

Retained from the source plan, all correct:

- Do not rewrite the application. Do not replace PostgreSQL. Do not replace the durable queue because Celery exists.
- Do not migrate the React app to Next.js. No Kafka. No microservices. No Kubernetes because manifests exist.
- Do not build more AI agents before the existing pipeline works.
- Do not add providers until provider behaviour is normalized.
- Do not expose half-implemented features.
- **Do not let "code exists" count as "capability exists."**

Added:

- Do not build adapters to preserve two incompatible designs (§4.5). Delete one.
- Do not fix `docker-compose.yml` or `k8s/` unless CI exercises them. Otherwise move them under `experimental/` and document one supported deployment (§4.15).
- Do not treat this as a security program (§0). Auth work is in scope only where §4.10 makes it a functional blocker.

---

## 11. Risks to this plan

| Risk | Mitigation |
|---|---|
| P0.2 (durable chapter artifacts) is larger than it looks — it touches the pipeline, streaming, rerender, and export | Sequence it early and alone. Everything downstream depends on it. Do not parallelize it with P0.3. |
| The `/v1` → `/api` merge is not a route copy — identity must be threaded through every handler (§4.10) | Budget for it explicitly. Estimate per-endpoint, not per-file. |
| Deleting `v1_api.py` loses work someone values | The logic moves to `backend/services/*`. Nothing is discarded; the transport layer is. Say so in the PR. |
| The 2 GPU-synthesis test failures may be environment-only | Confirm against GitHub Actions before spending time on them. |
| Disabling `main.yml` reads as removing capability | It produces daily unreviewable churn against a codebase that does not build. Re-enable later as analysis-only → branch → PR → mandatory CI → human merge. |
| The matrix becomes decorative | It is a merge gate, not a document. Enforce it in review. |

---

## 12. The standard for "ACX City fully works"

```
I upload a book.
    ↓  ACX City understands its structure.
    ↓  I assign voices and pronunciations.
    ↓  It produces chapters.
    ↓  I can listen immediately.
    ↓  Something sounds wrong.
    ↓  I change one character, one word, one chapter.
    ↓  Only affected material re-renders.
    ↓  A provider temporarily fails      →  it recovers automatically.
    ↓  The worker crashes                →  the job resumes.
    ↓  The application restarts          →  nothing is lost.
    ↓  QC confirms the audio.
    ↓  I export the audiobook.
    ↓  The exported book is complete, ordered, playable and reproducible.
```

The conceptual shift the source plan identifies is the right one and bears repeating: **stop measuring progress by how many modules, endpoints, agents, manifests or panels exist. Measure it by how many complete user capabilities survive failure from beginning to end.**

The evidence supports optimism. The old surface — durable queue, ownership model, billing ledger, QC gate, storage abstraction, retention — is genuinely well built and well tested, and 119 tests pass against it. Almost every S1/S2 defect in this document lives in code that no test imports. The core is not the problem. The untested expansion around it is, and it is recoverable.

**The first five battles, in order: make it build, make chapters durable, one API, one worker path with a real lease, and a ruthless end-to-end test suite. Everything else gets dramatically easier once those five are true.**
