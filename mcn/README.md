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

The two tokens are also picked up from the process environment when
`.env.local` is absent — set `RAILWAY_TOKEN` and `VERCEL_TOKEN` as CI
secrets or Cursor Cloud Agent secrets (Cursor Dashboard → Cloud Agents →
Secrets) and agents can run the provisioner unattended.

## Usage

```bash
cd mcn
pip install pyyaml
python3 bootstrap_railway.py --dry-run   # preview Railway project creation
python3 bootstrap_railway.py            # create project/services/volumes/DBs
python provision.py --dry-run            # preview the env-var plan
python provision.py                      # push everything
```

`bootstrap_railway.py` replaces every Railway dashboard click: it creates the
`acx-city` project, the three repo services, Postgres, MinIO object storage
(Railway volumes cannot be shared between services, so backend and worker use
S3-mode storage instead of a shared disk), volumes, public domains, and the
cross-service reference variables. It is idempotent — rerun any time.

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
