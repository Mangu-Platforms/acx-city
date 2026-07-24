# ADR 0001 — Adopt Supabase Auth and object storage (via a pluggable backend)

- Status: Accepted
- Date: 2026-07-24
- Deciders: Renee (MANGU), engineering
- Applies MANGU rule #3 (short ADR before changing the auth provider or primary
  data/storage service).

## Context

The audiobook tool reached its "durable foundation" milestone with a Postgres
system-of-record, a restart-safe worker queue, and **custom** bcrypt + JWT auth.
Two blueprint items remain: object storage with signed URLs, and aligning to the
MANGU Web Platform baseline, which names **Supabase** as the canonical provider
for Postgres, auth, storage, and RLS, and says to pick exactly one canonical
auth provider per project.

Rolling our own auth diverges from that baseline and duplicates functionality
Supabase already provides (email/OAuth, password reset, session management).
Local-filesystem storage does not meet the durability/security bar (no signed
URLs, no retention, not horizontally shareable beyond a mounted volume).

## Decision

1. **Auth → Supabase Auth.** The API verifies Supabase-issued JWTs. Local
   `User`/`Organization` rows are provisioned just-in-time from the token's
   subject/email on first authenticated request, preserving our ownership model
   and multi-tenant scoping. The request guard's public interface
   (`require_auth`, `current_identity`) is unchanged, so views don't change.

2. **Storage → object storage behind a `StorageBackend` interface.** Manuscripts
   and rendered audio are stored as keys, not local paths. Two implementations:
   - `LocalStorage` — filesystem, for dev/sandbox/tests (no cloud creds needed).
   - `SupabaseStorage` — Supabase Storage over its S3-compatible gateway; issues
     time-limited **signed URLs** for downloads.
   The backend is selected by `STORAGE_BACKEND` env.

3. **Back-compat / transition.** A `AUTH_MODE` flag selects `supabase` (verify
   Supabase JWTs) or `legacy` (the existing bcrypt/JWT path). `legacy` remains
   the default in tests and for any deployment not yet on Supabase, so this ADR
   ships without forcing an immediate cutover. New deployments set
   `AUTH_MODE=supabase`.

## Consequences

Positive:
- One canonical auth provider; less security-sensitive code to own.
- Durable, signed, expiring download URLs; storage no longer tied to a host volume.
- Storage interface keeps tests runnable offline and keeps us portable (the same
  interface works for Supabase, MinIO, R2, or S3).

Negative / risks:
- Two auth modes exist during transition; must be clearly documented and the
  legacy path eventually removed via a follow-up ADR.
- Supabase JWT verification needs the project's JWT secret / JWKS configured;
  misconfiguration fails closed (401), which is the safe direction.
- Just-in-time provisioning must be idempotent under concurrent first requests.

## Non-goals (explicitly out of scope, per the MANGU skill)

- Not adopting Supabase as the primary application database in this phase (we
  keep our own Postgres + Alembic migrations; RLS is a later, separate decision).
- Not migrating the Vite SPA to Next.js. MANGU's Next.js default is for new
  full-stack/product apps; this tool keeps its SPA and applies MANGU's shared
  practices (TypeScript, Tailwind, Zod, env discipline, tests, CI, security).
- No MANGU-Publishers product models/content are imported.

## Verification

- Storage: unit tests for the local backend (put/get/signed-url/delete) run in CI
  without cloud creds; the Supabase backend is exercised in environments that set
  `STORAGE_BACKEND=supabase` + credentials.
- Auth: unit tests verify Supabase-style HS256 JWTs are accepted and that invalid
  / expired / wrong-audience tokens are rejected; the legacy path keeps its tests.
