# MCN Control Plane

One place to manage environment configuration for every service in the MCP
Network. **You never touch a Railway or Vercel env-var dashboard again.**

## How it works

- **`registry.yaml`** — declares every repo, service, and env var in the
  network. Secrets are declared once and shared across services; public URLs
  are cross-referenced (`${url:railway:backend}`) and resolved live from the
  platform APIs.
- **`provision.py`** — reads the registry, generates any missing secrets
  (persisted to `.secrets.json`, gitignored), and upserts all vars to Railway
  and Vercel via their APIs. Idempotent: rerun any time.

## One-time setup

Create `mcn/.env.local` (gitignored) with two tokens:

```
RAILWAY_TOKEN=...   # railway.app → Account Settings → Tokens
VERCEL_TOKEN=...    # vercel.com → Settings → Tokens
# VERCEL_TEAM_ID=...  # only for team accounts
```

That is the entire manual surface, forever.

## Usage

```bash
cd mcn
pip install pyyaml
python provision.py --dry-run   # preview the plan
python provision.py             # push everything
```

First run after creating fresh Railway/Vercel projects: the cross-referenced
URLs (`CORS_ALLOW_ORIGINS`, `NEXT_PUBLIC_API_URL`) show as `<PENDING>` until
each platform has assigned a public domain — deploy once, rerun, resolved.

## Adding a repo to the network

Add a block under `repos:` in `registry.yaml` (copy the acx-city shape),
rerun `provision.py`. Shared secrets like `MCP_API_KEY` fan out automatically
to any service that references them.

## Notes

- `DATABASE_URL` is injected by Railway's Postgres plugin — never listed here.
- Secrets live only in `.secrets.json` on your machine and in the platforms'
  encrypted stores. Nothing sensitive is committed.
