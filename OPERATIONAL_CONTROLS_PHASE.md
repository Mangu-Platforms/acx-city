# Phase 4 — operational controls

The "safe to run in front of real users and real bills" layer: a cost ledger,
per-org quotas and rate limiting, QC gating, retention/lifecycle cleanup, and
structured logging. All built on the existing Postgres foundation, no new
required infrastructure.

## What was built

### Cost ledger (`backend/billing/`)
- `UsageEvent` model — one row per billable (paid-provider, non-cached) chunk,
  bucketed by `YYYY-MM` for fast monthly rollups.
- Providers now declare `cost_per_million_chars` (Polly ≈ $16/M; Edge = 0).
- The pipeline records usage as it synthesizes; `GET /api/usage` returns
  characters, cost, quota, and remaining for the current month.

### Quotas + rate limiting (`backend/ratelimit/`)
- Per-org monthly character quota (`Organization.monthly_char_quota`, global
  `QUOTA_MONTHLY_CHARS` default). Job creation returns **402** when exceeded;
  free providers never count against quota.
- Per-org job-creation rate limit (**429**), backends: `postgres` (fixed-window
  counter in `rate_buckets`, default), `upstash` (Redis REST, MANGU baseline),
  or `none`.

### QC gating (`QC_POLICY` = off | warn | block)
- `block` holds jobs with failing chapters in a new `needs_review` status instead
  of shipping them. Reviewers can download to listen, then `approve`
  (→ succeeded) or `reject` (→ failed). Per-org override via `Organization.qc_policy`.

### Retention / lifecycle (`backend/jobs/retention.py`)
- `DELETE /api/jobs/<id>` removes a job and its stored assets on demand.
- A worker-scheduled sweeper deletes terminal jobs' audio past `RETENTION_DAYS`
  (per-org override), optionally deleting rows too (`RETENTION_DELETE_ROWS`).

### Observability (`backend/observability/`)
- Structured **JSON logs** (or text in dev) with a **request-id** contextvar
  correlating API requests and worker jobs; responses carry `X-Request-Id`.
- **Secret redaction**: `password`, `token`, `source_text`, AWS/S3 secrets, etc.
  are never logged (redacted to `***`).
- Optional **Sentry** via `SENTRY_DSN` (lazy import; `send_default_pii=False`).

## Data model / migrations
- New: `usage_events`, `rate_buckets`; `organizations` gains
  `monthly_char_quota`, `qc_policy`, `retention_days`; `jobs.status` adds
  `needs_review`. Alembic migrations included; upgrade/downgrade verified.

## Verification

Sandbox run (SQLite), all green:
- `pytest -q` → **51 passed, 1 skipped** (the skip is the Postgres-only
  concurrency test). New tests cover: ledger + quota math; API 402 (quota) and
  429 (rate limit) and the usage endpoint; the Postgres rate-limiter window;
  QC gating (block holds, warn ships, approve/reject); retention (asset delete,
  window-respecting sweep, delete endpoint); and structured-logging redaction.
- `ruff check .` → **All checks passed**.
- Frontend `tsc` / `eslint` / `vite build` → unchanged and green.

### Sandbox caveat (unchanged)
No live Postgres/Supabase/S3/Upstash/Sentry in the build sandbox, so those
backends run via their interfaces with local/stubbed equivalents and the
Postgres-only concurrency test auto-skips. The code is written backend-first and
CI is wired to run against real Postgres.

## A cross-backend fix worth noting
SQLite drops timezone info on datetime round-trips, which surfaced a real
comparison bug in the retention sweep (`aware > naive`). Fixed at the source by
normalizing persisted timestamps to UTC before comparing — correct on both
Postgres and SQLite.
