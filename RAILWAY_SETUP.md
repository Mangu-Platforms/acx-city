# Railway Deployment — ACX City

Step-by-step guide to deploy the full stack (backend API, worker, frontend,
Postgres) on [Railway](https://railway.app).

---

## Prerequisites

- A [Railway account](https://railway.app) (free tier works to start)
- This repo connected to your Railway project (GitHub → Railway)

---

## Step 1 — Create a new Railway project

1. Go to [railway.app/new](https://railway.app/new)
2. Click **Deploy from GitHub repo** → select `redinc23/acx-city`
3. Railway will detect `railway.toml` and scaffold the three services
   (`backend`, `worker`, `frontend`) automatically.

---

## Step 2 — Add a Postgres database

1. In your project dashboard click **+ New** → **Database** → **PostgreSQL**
2. Railway provisions Postgres and automatically injects `DATABASE_URL` into
   every service in the project. No manual wiring needed.

---

## Step 3 — Volume and the combined API + worker service

The backend and worker must share the same `/data` directory so synthesized
audio produced by the worker is accessible to the API for downloads.

> ⚠️ Railway mounts a volume to **exactly one service** — a volume cannot be
> shared between two services. So with the default local storage backend, the
> API and worker run as **one combined service** using
> [`backend/railway.combined.toml`](./backend/railway.combined.toml), which
> starts both processes via `start_combined.sh`.

1. On the app service: **Settings** → set **Root Directory** to `backend` and
   **Config File** to `backend/railway.combined.toml`
2. Click **+ New** → **Volume**, name it `audiobook-data`, attach it to the
   service at mount path `/data`

To run the worker as a separate Railway service (e.g. to scale it
independently), switch to object storage first: set `STORAGE_BACKEND=s3` on
both services so they no longer need a shared filesystem, then deploy the
worker with `backend/railway.worker.toml`.

---

## Step 4 — Set required environment variables

Set these in the Railway dashboard under each service's **Variables** tab.

### On `backend` and `worker` (both need these)

| Variable | Value | Notes |
|---|---|---|
| `JWT_SECRET` | `openssl rand -hex 32` | **Required in prod.** Never commit this. |
| `POSTGRES_PASSWORD` | any strong password | Must match what you used if you overrode the default |
| `CORS_ALLOW_ORIGINS` | `https://your-frontend.up.railway.app,https://your-dashboard.vercel.app` | Comma-separated, no spaces. Include the frontend (Railway) **and** the admin dashboard (Vercel) origins. See [VERCEL_SETUP.md](./VERCEL_SETUP.md). |

### On `backend` only

| Variable | Value |
|---|---|
| `AUTH_MODE` | `legacy` (default) or `supabase` |
| `QC_POLICY` | `warn` (default), `block`, or `off` |
| `QUOTA_MONTHLY_CHARS` | `0` (unlimited) or a character limit per org |

### On `frontend` only

| Variable | Value | Notes |
|---|---|---|
| `BACKEND_PRIVATE_URL` | `http://backend.railway.internal:5000` | Railway private network URL — use this exact format, replacing `backend` with your backend service's private domain if different |

> To find the private domain: open the `backend` service → **Settings** →
> **Networking** → copy the **Private Domain**.

---

## Step 5 — (Optional) Custom domain + TLS

Railway provisions a free `*.up.railway.app` subdomain with TLS for every
public service automatically. To use a custom domain:

1. Open the service → **Settings** → **Domains** → **+ Custom Domain**
2. Add a `CNAME` record in your DNS provider pointing to the Railway domain
3. Railway auto-provisions a Let's Encrypt certificate

---

## Step 6 — Deploy

Once variables are set, click **Deploy** (or push a commit to `main` — CI
auto-deploys). Watch the build logs. Order of readiness:

1. `db` — Postgres starts (30–60 s)
2. `backend` — runs `alembic upgrade head` then starts Gunicorn
3. `worker` — connects to DB, starts polling for jobs
4. `frontend` — nginx starts, substitutes backend URL into config

Health checks are wired; Railway will restart any service that fails its check.

---

## Step 7 — Verify

```bash
# Health check (replace with your backend Railway URL)
curl https://your-backend.up.railway.app/api/health

# Expected response (abridged):
# {"status": "healthy", "database": "ok", "providers": [...]}
```

Open `https://your-frontend.up.railway.app` — you should see the login/signup
screen.

---

## Admin dashboard (Vercel)

The Next.js admin dashboard (`dashboard/`) deploys on Vercel, not Railway.
Once the backend is live, follow [VERCEL_SETUP.md](./VERCEL_SETUP.md) — set
`NEXT_PUBLIC_API_URL` to the backend's public URL and add the Vercel origin to
the backend's `CORS_ALLOW_ORIGINS` (Step 4 above).

---

## Scaling workers

To handle more concurrent synthesis jobs, scale the worker horizontally in
Railway:

1. Open the `worker` service → **Settings** → **Replicas** → increase count
2. The `FOR UPDATE SKIP LOCKED` job queue ensures multiple workers never claim
   the same job.

---

## Environment variable reference

Full list of supported variables: see [`.env.example`](./.env.example) at the
root of the repo.

---

## Cost estimate (Railway)

| Service | RAM | Approx cost/mo |
|---|---|---|
| backend (2 workers) | 512 MB | ~$5 |
| worker (1 replica) | 256 MB | ~$2 |
| frontend (nginx) | 64 MB | ~$1 |
| Postgres | 1 GB | ~$5 |
| Volume (10 GB) | — | ~$1 |
| **Total** | | **~$14/mo** |

Railway's free tier ($5 credit/mo) covers light testing. Production with real
users should use the Hobby plan ($20/mo) or higher.
