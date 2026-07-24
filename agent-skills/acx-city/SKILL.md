---
name: acx-city
description: Build, review, test, or operate the ACX City audiobook production platform. Use when working in this repository or on its Vite frontend, Flask API, PostgreSQL job queue, worker, storage, Supabase authentication, Docker deployment, or GitHub Actions CI.
---

# ACX City

Read the shared `../mangu-web-platform/SKILL.md` first, then apply these
project-specific rules.

## Architecture

- Keep the frontend as a **Vite + React + TypeScript + Tailwind SPA**. Do not
  migrate it to Next.js without a written product/architecture decision.
- Keep the API and worker as a **Flask/Python** service under `backend/`.
- Treat PostgreSQL, SQLAlchemy, and Alembic migrations as the production system
  of record. SQLite supports local development only.
- Treat jobs as durable database rows. Preserve `FOR UPDATE SKIP LOCKED`, retry,
  orphan-recovery, cancellation, and organization-ownership controls.
- Use the storage abstraction: local storage for development and S3-compatible
  storage/Supabase Storage for production. Downloads must remain signed and
  time-limited.
- `AUTH_MODE` may select Supabase JWT verification or the documented legacy
  path. Do not change the default or remove a provider without an ADR and a
  migration plan.

## Safety rules

1. Enforce authenticated, organization-scoped access to jobs, files, usage,
   and administrative actions; an ID alone is never authorization.
2. Preserve server-side upload allowlists and scoped CORS.
3. Keep generated audio, uploads, output files, caches, local databases, and
   `.env` files out of Git.
4. Never expose S3, Supabase, JWT, AWS, Sentry, or rate-limit credentials to
   the browser, repository, logs, or agent output.
5. Keep frontend API URLs configurable through environment variables and the
   Vite development proxy; do not hardcode a deployed backend URL.

## Verification

Run the applicable checks before calling work complete:

```bash
cd backend
pytest -q

cd ../frontend
npm ci
npm run lint
npm run build
```

For database or concurrency changes, also run the test suite against PostgreSQL
so the `SKIP LOCKED` test executes. Confirm Alembic migrations apply from a
clean database. For production-impacting changes, inspect `docker-compose.yml`,
the Dockerfiles, and `.github/workflows/ci.yml`.
