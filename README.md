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

## Webhook security

The backend receives GitHub App events at `POST /api/webhooks/github` and
verifies every request's `X-Hub-Signature-256` HMAC against
`GITHUB_WEBHOOK_SECRET`. In production the secret is **required** — with it
unset the endpoint rejects all requests; in dev, verification is skipped with
a warning so local experiments work. Generate one with
`openssl rand -hex 32` and set the same value in both the backend env
(`GITHUB_WEBHOOK_SECRET`, see `mcn/registry.yaml`) and the GitHub App's
webhook settings.

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

Remaining items, in rough priority order:

- **Retire the legacy auth path** once all deployments are on Supabase (follow-up ADR).
- **Metrics & tracing** beyond logs (Prometheus/OpenTelemetry).
- **Billing integration** (Stripe per MANGU) to turn the cost ledger into invoices.
- **RLS** if/when Supabase becomes the primary database (separate ADR).
- **MCP network (MCN)**: `backend/mcp_server.py` is the first node — a
  streamable-HTTP MCP server (gated by `MCP_ENABLED` + `MCP_API_KEY`, see
  `backend/railway.mcp.toml`) exposing read tools (`acx_health`,
  `acx_list_jobs`, `acx_get_job`, `acx_list_organizations`, `acx_usage`) and,
  behind the additional `MCP_WRITE_ENABLED=true` gate, write tools
  (`acx_cancel_job`, `acx_approve_job`, `acx_reject_job`) that reuse the REST
  API's queue semantics. Next: sibling repos joining the network.

See the Revamp Blueprint for the full target architecture and delivery roadmap.

## Notes

- Synthesized chunks are cached (content-addressed by provider+voice+text hash).
- Final outputs land under the configured `OUTPUT_FOLDER` per task id (per-chapter MP3s plus merged MP3/M4B).
