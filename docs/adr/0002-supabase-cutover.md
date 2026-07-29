# ADR 0002 — Execute the Supabase cutover (auth + storage) for production

- Status: Proposed (becomes Accepted when Phase C completes)
- Date: 2026-07-29
- Deciders: Renee (MANGU), engineering
- Follows ADR 0001, which adopted Supabase Auth + object storage behind
  `AUTH_MODE` / `STORAGE_BACKEND` flags but deliberately deferred the
  production cutover.

## Context

Production (the Railway combined backend+worker service) still runs
`AUTH_MODE=legacy` and `STORAGE_BACKEND=local` against the service volume.
ADR 0001's roadmap item — "retire the legacy auth path" — needs a concrete,
reversible plan. The infrastructure now exists: Supabase project **acx-city**
(ref `kmkhyffdnsnaqkqnaexk`, us-east-1) with a private **audiobooks** storage
bucket. The backend already supports both modes; `backend/auth/supabase.py`
provisions users just-in-time, mapping by token `sub` and **falling back to
email**, so existing legacy accounts link automatically on first Supabase
login (org membership preserved).

## Decision

Cut production over in four phases. The legacy code path remains untouched
until Phase D, so Phases A–C are reversible by env var alone.

### Phase A — Backend verification (no user impact)

- Add to the Railway backend service (additive; no mode flip yet):
  - `SUPABASE_JWKS_URL=https://kmkhyffdnsnaqkqnaexk.supabase.co/auth/v1/.well-known/jwks.json`
  - `SUPABASE_JWT_AUD=authenticated`
- Create one test user in Supabase Auth. Verify its access token against a
  local/staging run with `AUTH_MODE=supabase`; confirm JIT provisioning and
  the email-linking fallback (`backend/tests/test_supabase_auth.py`).

### Phase B — Client login swap

- SPA (`frontend/`) and ops dashboard (`dashboard/`): replace
  `POST /api/auth/login|signup` with `supabase-js`
  (`signInWithPassword` / `signUp`) and send the Supabase access token as
  `Authorization: Bearer`.
- Env: `VITE_SUPABASE_URL` + publishable key (SPA);
  `NEXT_PUBLIC_SUPABASE_URL` + publishable key (dashboard). Publishable keys
  are safe for browsers; never ship the secret/service key.
- Deploy clients before the backend flip (both token styles hit the same
  `Authorization` header; the backend decides by `AUTH_MODE`).

### Phase C — Flip auth + storage

- Backend env: `AUTH_MODE=supabase`, plus
  `STORAGE_BACKEND=s3`,
  `STORAGE_S3_ENDPOINT=https://kmkhyffdnsnaqkqnaexk.supabase.co/storage/v1/s3`,
  `STORAGE_S3_REGION=us-east-1`, `STORAGE_S3_BUCKET=audiobooks`,
  `STORAGE_S3_ACCESS_KEY` / `STORAGE_S3_SECRET_KEY` (minted in Supabase
  Dashboard → Storage → S3 access keys).
- Existing audio on the `/data` volume: either (a) one-time copy of
  `storage_data/` into the bucket, or (b) accept re-synthesis — the
  content-addressed cache makes rerenders cheap. Pick (a) only if pre-flip
  jobs must stay downloadable.
- Verify: login via both clients, one job end-to-end, signed URL served from
  the bucket, cross-org 403 spot check.

### Phase D — Retire legacy (separate follow-up PR)

- Remove `/api/auth/signup|login` and the bcrypt path; drop `AUTH_MODE`;
  keep `STORAGE_SIGNING_SECRET` for local-mode HMAC in dev. Update tests,
  `.env.example`, README, and `agent-skills/acx-city/SKILL.md`.
- Gate: at least two weeks of stable Supabase auth in production.

## Rollback

Phases A–C: revert `AUTH_MODE=legacy` + `STORAGE_BACKEND=local` — instant,
no data loss (legacy users/rows are never modified). Phase D is the only
irreversible step, hence the stability gate.

## Consequences

- One canonical auth provider (MANGU baseline rule); password reset, OAuth,
  and session management stop being our code to own.
- Durable storage with signed URLs, decoupled from the Railway volume.
- Cost: Phase B is the real work (two login surfaces + token plumbing);
  S3 access keys become a managed secret; a third-party dependency sits in
  the login path.

## Manual steps (cannot be automated without tokens)

1. Supabase Dashboard → `acx-city` → Storage → mint S3 access keys.
2. Set the Railway env vars above (or provide `RAILWAY_TOKEN` so
   `mcn/provision.py` can push them from `registry.yaml`).
3. Supabase Auth settings: confirm email sign-in defaults; leave magic
   links/OAuth off unless wanted.

## Verification

- Phase A: token verify + JIT idempotency tests green.
- Phase C: e2e job with signed bucket download; legacy endpoints still 200
  (unused) until Phase D removes them.
