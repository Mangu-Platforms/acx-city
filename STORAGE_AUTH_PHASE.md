# Phase 3 — object storage, signed URLs, and Supabase auth alignment

This phase adds durable object storage with expiring signed download links and
aligns authentication to the MANGU Web Platform baseline (Supabase), while
keeping everything testable offline. Decisions are recorded in
[docs/adr/0001](./docs/adr/0001-supabase-auth-and-storage.md).

## What was built

### Object storage (`backend/storage/`)
- `StorageBackend` interface over opaque keys (`org/<org>/jobs/<job>/audiobook.mp3`).
- `LocalStorage` — filesystem backend for dev/sandbox/tests. Issues **signed
  URLs** pointing at an app route (`/api/files/<key>`) protected by an HMAC token
  + expiry, so the download UX matches the cloud path with no cloud creds. Guards
  against path traversal.
- `S3Storage` — boto3 against any S3-compatible endpoint (**Supabase Storage**
  via its S3 gateway, plus AWS S3 / R2 / MinIO). Uses native presigned URLs.
- `STORAGE_BACKEND` env selects the implementation.
- The pipeline now uploads rendered MP3/M4B to storage and records
  `output_mp3_key` / `output_m4b_key` (new columns + Alembic migration). Legacy
  path columns are retained for back-compat.

### Signed-URL downloads
- `GET /api/download/<id>` returns `{url, expires_in}` instead of streaming bytes
  (add `?redirect=1` to 302 to the file). Authorization to *get the link* is still
  org-scoped; the link itself is time-limited and, for the local backend,
  HMAC-signed and verified by `/api/files/<key>`.

### Supabase Auth (`backend/auth/supabase.py`, guard changes)
- `AUTH_MODE=supabase` verifies Supabase JWTs (HS256 via `SUPABASE_JWT_SECRET`,
  or RS256/ES256 via `SUPABASE_JWKS_URL`), checks audience + expiry, and
  provisions a local `User` + personal `Organization` just-in-time on first
  request (idempotent). The guard's public interface is unchanged, so all views
  and ownership checks keep working.
- `AUTH_MODE=legacy` (default) keeps the built-in bcrypt/JWT path, so this ships
  without forcing an immediate cutover.

### Frontend (MANGU practices, still Vite — no Next.js migration)
- **Zod** schemas (`src/lib/schemas.ts`) validate the synthesis request and
  auth/signed-URL responses at the boundary.
- Download flow updated to fetch a signed URL and follow it.
- Auth token handling and login gate carried over from phase 2.

### Ops & docs
- `.env.example`, `docker-compose.yml` (shared storage volume + `STORAGE_*`
  vars), README, and the ADR updated. `boto3` (already a dependency for Polly) is
  reused for S3; no new backend dependency required for storage.

## MANGU alignment notes

Applied from the [skill](./SKILL.md) where it fits this tool:
- One canonical auth provider (Supabase) selected; legacy path is transitional.
- Supabase Storage as the canonical object store, behind a portable abstraction.
- Zod validation, environment discipline (no secrets in code/examples), a health
  endpoint, and clear server-only credential handling.

Deliberately **not** done, per the skill and your guidance:
- No Next.js migration — this tool keeps its Vite SPA. (Revisit only if it needs
  SSR/SEO/route handlers or a unified full-stack architecture.)
- Supabase is not adopted as the primary application DB in this phase; we keep
  our own Postgres + Alembic. RLS remains a separate future decision.
- No MANGU-Publishers product models/content imported.

## Verification

Sandbox run, all green:
- `pytest -q` → **32 passed, 1 skipped** (the skipped one is the Postgres-only
  `FOR UPDATE SKIP LOCKED` concurrency test; it runs in CI against Postgres).
  New tests: storage put/get/sign/verify/expiry/traversal; Supabase token
  verification (valid / expired / wrong-signature / wrong-audience / missing) and
  idempotent JIT provisioning; end-to-end signed-URL download incl. tampered-link
  and cross-org rejection.
- `ruff check .` → **All checks passed**.
- Alembic upgrade/downgrade round-trip for the new key columns → OK.
- Frontend `tsc --noEmit` → pass; `vite build` → built (Zod included); `eslint` → clean.

### Sandbox caveat (unchanged from phase 2)
No live Postgres, Supabase, or S3 was reachable in the build sandbox, so cloud
backends are exercised via their interfaces with local/stubbed equivalents and
the concurrency test auto-skips. Point `STORAGE_BACKEND=s3` + `AUTH_MODE=supabase`
(with credentials) in a real environment to exercise the cloud paths; the code
and CI are wired for it.
