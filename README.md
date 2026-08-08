# Audiobook Production Tool

A full-stack audiobook production tool: a **Flask** backend with pluggable TTS
providers (free Microsoft Edge voices + optional AWS Polly), and a
**React + TypeScript + Vite + Tailwind** frontend.

> **Status: production-ready foundation + operational controls.**
> Building on the [Revamp Blueprint](./Audiobook_Production_Platform_Revamp_Blueprint.docx),
> four phases are done: **repository rescue** (safe deploy/config), the
> **durable foundation** (Postgres system-of-record, restart-safe workers,
> multi-tenant auth), **object storage + Supabase auth** (signed URLs, aligned to
> the [MANGU](./SKILL.md) baseline), and **operational controls** (cost ledger,
> per-org quotas + rate limiting, QC gating, retention, structured logging).
> See [docs/adr/0001](./docs/adr/0001-supabase-auth-and-storage.md), the
> [operational controls](#operational-controls), and the [roadmap](#roadmap).

## Architecture

```
                         ┌──────────────┐
  Browser ──/api──▶ nginx│  frontend    │
                         └──────┬───────┘
                                │ proxy /api
                         ┌──────▼───────┐        ┌──────────────┐
                         │  backend     │  RW    │  PostgreSQL  │
                         │  (gunicorn)  │───────▶│  system of   │
                         └──────────────┘        │  record      │
                         ┌──────────────┐  claim │  + job queue │
                         │  worker(s)   │◀───────│              │
                         │  (pipeline)  │───────▶│              │
                         └──────────────┘  RW    └──────────────┘
```

- **System of record:** PostgreSQL via SQLAlchemy 2.0, schema managed by Alembic.
  Organizations, Users, Memberships, Projects, Jobs, ChapterResults, JobAttempts.
- **Durable job queue:** jobs are rows. Workers claim the next one with
  `SELECT ... FOR UPDATE SKIP LOCKED`, so multiple workers never grab the same
  job and a crash simply leaves the row for another worker or the orphan sweeper.
- **Restart safety:** progress is checkpointed to the DB per chapter; on startup
  (and periodically) the worker requeues jobs whose worker died mid-run.
- **Auth & tenancy:** org-scoped ownership checks — a job/task id no longer
  authorizes access; the caller must belong to the owning organization (cross-org
  access returns 403). `AUTH_MODE` selects **Supabase Auth** (verify Supabase
  JWTs, provision users just-in-time) or the built-in **legacy** bcrypt/JWT path.
- **Object storage:** manuscripts and audio are stored by key behind a
  `StorageBackend` interface — `local` (dev) or `s3` (Supabase Storage / S3 / R2 /
  MinIO). Downloads return **time-limited signed URLs**; bytes are not streamed
  through business endpoints.

## Features

- Upload DOCX, TXT, or PDF — or paste text directly
- Automatic chapter detection (DOCX headings become chapters; text headings like "Chapter 1" are detected heuristically)
- Pluggable TTS providers behind one interface:
  - **Microsoft Edge neural voices** — free, no API key, works out of the box
  - **AWS Polly** — enabled automatically if AWS credentials are set
- Content-addressed synthesis cache: re-running a book only synthesizes changed text
- Per-chapter QC checks: duration, loudness, silence ratio, clipping — warnings shown in the UI
- Downloads: merged **MP3** and **M4B with real chapter markers** (Apple Books, BookPlayer, etc.)
- Dockerized services (non-root, health-checked) and GitHub Actions CI

## VoxEngine Multi-Agent Pipeline (Phase 5+)

The core differentiator: five specialized LLM agents that prepare, normalize, tag, plan, and validate every paragraph before synthesis.

````
Raw Manuscript → Agent 1 (Structure Parser) → Agent 2 (Character Attribution)
  → Agent 3 (Text Normalizer) → Agent 4 (Prosody Planner) → Agent 5 (QA Validator)
  → Fully Tagged Script → GPU Synthesis
````

| Agent | Model | Cost/1M chars | Purpose |
|-------|-------|---------------|--------|
| 1: Structure Parser | Rule-based | $0.00 | Chapter/scene/paragraph detection |
| 2: Character Attribution | Llama-3.2-3B | $0.05 | Speaker identification |
| 3: Text Normalizer | gpt-4o-mini | $0.15 | Numbers, abbreviations, heteronyms |
| 4: Prosody Planner | Phi-3.5-mini | $0.08 | Emotion tags, pauses, rate changes |
| 5: QA Validator | gpt-4o-mini | $0.10 | Completeness, consistency, tag validity |

**Emotion tag vocabulary** (superset of fish.audio S2.1):
`[angry]` `[sad]` `[whisper]` `[soft]` `[breathy]` `[excited]` `[embarrassed]`
`[laughing]` `[sobbing]` `[sighing]` `[pause:NNN]` `[scene_break:3000]`
`[rate:slow]` `[rate:fast]` `[emphasis]` `[SPEAKER:Name]`

### New endpoints (FastAPI /v1/* sidecar)

- `POST /v1/projects/:id/pipeline/start` — kick off multi-agent preprocessing
- `GET /v1/projects/:id/pipeline/status` — per-chapter pipeline status + costs
- `GET /v1/projects/:id/pipeline/trace/:chapter` — full agent trace
- `GET /v1/projects/:id/characters` — character voice assignments
- `POST /v1/projects/:id/characters` — set character voice
- `GET /v1/projects/:id/lexicon` — pronunciation dictionary
- `POST /v1/projects/:id/lexicon` — add pronunciation entry
- `GET /v1/voices` — voice catalog (paginated, filterable)
- `GET /v1/voices/:id` — voice detail + emotion tags

### MCP write tools (Phase 5)

- `acx_cancel_job` — cancel a running/queued job
- `acx_approve_job` — approve QC-held job
- `acx_enqueue_synthesis` — enqueue new synthesis job
- `acx_get_pipeline_status` — pipeline status for a project

### Run with pipeline workers

```bash
cp .env.example .env  # Set REDIS_URL, OLLAMA_ENDPOINT, OPENAI_API_KEY
docker compose up --build
# Pipeline workers scale with: docker compose up --scale pipeline-worker=4
```

See the [VoxEngine Production Bible](./docs/) for the full specification.

---

## What changed

### Phase 2 — durable foundation

- **Postgres system-of-record** (SQLAlchemy 2.0 + Alembic migrations) replaces
  the in-memory `active_tasks` dict.
- **Durable job queue + standalone worker** (`worker.py`) using
  `FOR UPDATE SKIP LOCKED`; restart-safe with orphan recovery, retry/backoff,
  and cancellation.
- **Auth + multi-tenancy** — users, organizations, memberships; bcrypt + JWT;
  every project/job scoped to the caller's org with ownership checks (cross-org
  access is 403). Frontend gained a login/signup gate.
- **Migrations run automatically** on backend container start; compose now
  includes `db` + `worker` services.
- **Integration tests** cover job lifecycle, restart recovery, retry, cancel,
  and cross-org isolation (plus a Postgres-only concurrency test).

### Phase 1 — repository rescue (blueprint "first 72 hours")

- **Vite entry moved** to `frontend/index.html` (was `frontend/public/index.html`); `npm run build` works from a clean checkout.
- **CI moved** to `.github/workflows/ci.yml` with deterministic `npm ci`, ruff lint, and both build/test jobs.
- **No hardcoded API URL** — the frontend resolves `VITE_API_BASE_URL` or falls back to same-origin `/api` (dev-proxied to the backend in `vite.config.ts`).
- **Server-side upload allowlist** — the backend rejects any file that isn't `.txt/.pdf/.docx` by extension and declared MIME type. The browser `accept` attribute is treated as UX only.
- **Scoped CORS** — defaults to the local dev origin, not `*`.
- **Production process model** — containers run **gunicorn** via a WSGI entry (`backend/wsgi.py`), not the Flask dev server; the frontend is served as static assets by nginx.
- **Hardened containers** — non-root users, `tini` for signal handling, `HEALTHCHECK`s, and configurable storage paths so a container replacement doesn't erase cache/outputs (mounted volume).
- **Generated/private files removed** and blocked via `.gitignore` / `.dockerignore` (caches, bytecode, uploads, outputs, `.DS_Store`).
- **Deterministic lockfile** committed (`frontend/package-lock.json`).

## Prerequisites

- Python 3.10+, Node 18+
- `ffmpeg` on PATH (needed for audio assembly and M4B export)
- PostgreSQL for production (SQLite works for local dev with no setup)
- AWS account only if you want Polly — the app runs fully without it

## Quick start (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env      # set JWT_SECRET; DATABASE_URL optional (SQLite default)

alembic upgrade head         # create/upgrade the schema
python app.py                # API dev server (FLASK_ENV=development)
python worker.py             # in a second terminal: the job worker
```

API at `http://localhost:5000`. With no `DATABASE_URL`, it uses a local
`audiobook.db` SQLite file — fine for a single dev worker.

Production run: `gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 3600 wsgi:app`

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Frontend at `http://localhost:5173`, proxies `/api` to the backend. Sign up on
first use — the API is now authenticated.

## Run with Docker Compose

```bash
cp .env.example .env         # set JWT_SECRET (required) and POSTGRES_PASSWORD
docker compose up --build
```

Brings up **db** (Postgres), **backend** (gunicorn; runs migrations on start),
**worker**, and **frontend** (nginx). Frontend on `http://localhost:8080`,
backend on `http://localhost:5000`. Scale workers with
`docker compose up --scale worker=3`.

## Key API endpoints

Auth:
- `POST /api/auth/signup` — `{email, password, display_name?}` → `{token, user, organization}`
- `POST /api/auth/login` — `{email, password}` → `{token, user}`
- `GET /api/auth/me` — current user + active organization (auth required)

Discovery (public):
- `GET /api/providers` — available TTS engines
- `GET /api/voices?provider=edge|polly` — voices per engine

Work (auth required, org-scoped — send `Authorization: Bearer <token>`):
- `POST /api/upload` — multipart file upload (allowlisted types only)
- `POST /api/synthesize` — `{text, provider, voice_id, formats, title, author}` → enqueues a job
- `GET /api/jobs` — list this org's jobs
- `GET /api/task/<id>` (alias `GET /api/jobs/<id>`) — job status, per-chapter QC
- `POST /api/jobs/<id>/cancel` — request cancellation
- `POST /api/jobs/<id>/approve` — approve a QC-held job (`needs_review` → `succeeded`)
- `POST /api/jobs/<id>/reject` — reject a QC-held job (`needs_review` → `failed`)
- `DELETE /api/jobs/<id>` — delete a job and its stored audio
- `GET /api/usage` — this org's current-month usage and remaining quota
- `GET /api/download/<id>?format=mp3|m4b` — returns `{url, expires_in}`, a
  time-limited signed URL (add `?redirect=1` to 302 straight to the file)
- `GET /api/files/<key>?expires=…&sig=…` — serves a local-storage object for a
  valid signed link (unauthenticated; the signature is the grant). Cloud backends
  sign URLs that point directly at the object store instead.
- `GET /api/health` — health check incl. database connectivity

## Testing

```bash
cd backend && pytest -q          # runs against SQLite by default
# Against real Postgres (also runs the SKIP LOCKED concurrency test):
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/audiobook_test pytest -q

cd frontend && npm run lint && npm run build
```

## Operational controls

- **Cost ledger:** every billable (paid-provider, non-cached) chunk is recorded
  as a `UsageEvent`; `GET /api/usage` shows current-month characters, cost, and
  remaining quota.
- **Quotas & rate limits:** per-org monthly character quota (job creation returns
  402 when exceeded) and a per-org request rate limit (429). Rate-limit backend
  is `postgres` (default), `upstash`, or `none`.
- **QC gating:** `QC_POLICY` = `off` | `warn` (default) | `block`. `block` holds
  a job with failing chapters in `needs_review` for approve/reject.
- **Retention:** a worker sweeper deletes terminal jobs' audio past
  `RETENTION_DAYS` (per-org override supported); `DELETE /api/jobs/<id>` removes a
  job and its assets on demand.
- **Observability:** structured JSON logs with request-id correlation and secret
  redaction; optional Sentry via `SENTRY_DSN`.

## Roadmap

| Phase | Name | Status |
|-------|------|--------|
| 1–4 | Foundation & Infrastructure | ✅ COMPLETE |
| 5 | Multi-Agent LLM Pipeline | ✅ Code complete (agents, Celery, FastAPI, MCP write tools) |
| 6 | Character Attribution UI | ✅ Code complete (CharacterPanel component) |
| 7 | GPU Synthesis + Latent Pinning | ⬜ PLANNED (Kokoro-82M, Fish Speech integration) |
| 8 | WaveSurfer.js Studio | ✅ Code complete (MultiTrackStudio component) |
| 9 | Voice Catalog + Emotion Engine | ⬜ PLANNED (stock_voices seeding, emotion tag synthesis) |
| 10 | Voice Cloning | ✅ Code complete (VoiceCloneWorkbench, needs Fish Speech S2 backend) |
| 11 | Kubernetes + KEDA | ⬜ ROADMAP |

Remaining priorities:
- Seed stock_voices catalog with Edge + Polly voices
- GPU synthesis worker (Kokoro-82M / Fish Speech integration)
- Retire legacy auth path (Supabase migration)
- Prometheus + Grafana + OpenTelemetry observability
- Stripe billing integration
- Kubernetes + KEDA auto-scaling

## Notes

- Synthesized chunks are cached (content-addressed by provider+voice+text hash).
- Final outputs land under the configured `OUTPUT_FOLDER` per task id (per-chapter MP3s plus merged MP3/M4B).

## Remediation Program

Starting August 2026, ACX City is undergoing a structured remediation program to achieve reliable, crash-safe, end-to-end audiobook production. See [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) for per-feature status and phase progress.

## Autonomous Workflow

The daily multi-agent workflow (`.github/disabled/main.yml.disabled`) has been disabled. It generated unreviewable churn against a non-building codebase. It may be reconsidered after P1.8 (dashboard rebuild + worker heartbeat) if measurement justifies it.
