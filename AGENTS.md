# ACX City — Agent Instructions

Before planning, changing, reviewing, or deploying this repository, read:

1. [`agent-skills/mangu-web-platform/SKILL.md`](agent-skills/mangu-web-platform/SKILL.md)
2. [`agent-skills/acx-city/SKILL.md`](agent-skills/acx-city/SKILL.md)

The shared MANGU skill defines reusable engineering standards. The ACX City
skill defines this product's actual architecture and takes precedence wherever
the two differ.

Do not migrate the Vite frontend to Next.js solely to match the shared MANGU
default. Do not commit secrets, `.env` files, generated audio, uploads, caches,
or databases.

## Cursor Cloud specific instructions

The startup update script already installs all dependencies: the backend
virtualenv at `backend/.venv` (from `backend/requirements.txt` + `ruff`),
`frontend` (`npm ci`), and `dashboard` (`npm install`). `ffmpeg` is preinstalled
in the base image. This VM has **no Docker and no PostgreSQL** — develop against
SQLite (see below); `docker-compose.yml` / `railway.toml` are deploy-only.

Standard lint/test/build/run commands live in `README.md` and
`agent-skills/acx-city/SKILL.md` (Verification section). Non-obvious caveats:

- **Backend DB (SQLite):** `.env.example` ships `DATABASE_URL=` (empty), which
  makes SQLAlchemy raise `Could not parse URL from ''` — an empty value is NOT
  treated as "unset". For local dev copy it to `backend/.env` and set
  `DATABASE_URL=sqlite:///./audiobook.db` explicitly, plus a non-empty
  `JWT_SECRET`. Then run `alembic upgrade head` once (from `backend/`, venv
  active) to create the schema before starting the API/worker. The
  Postgres-only `FOR UPDATE SKIP LOCKED` test auto-skips on SQLite (expect
  `1 skipped` in pytest).
- **Run the app (dev):** with `backend/.venv` active, `python app.py` (API on
  `:5000`), `python worker.py` (job worker, second terminal). `frontend`:
  `npm run dev` (`:5173`, proxies `/api` to `:5000`). `dashboard`:
  `npm run dev` (`:3000`) and requires `NEXT_PUBLIC_API_URL=http://localhost:5000`
  (put it in `dashboard/.env.local`). The worker is a separate process — the API
  only enqueues jobs, so nothing synthesizes unless `worker.py` is running.
- **edge-tts:** the default free TTS provider talks to Microsoft over a
  WebSocket. Older pins (`6.1.12`) get a `403 Invalid response status` and every
  job fails "chunk synthesis failed after 3 attempts"; a current `edge-tts`
  (7.x) works. Outbound egress is open in this environment.
- **Frontend job-completion display is broken (pre-existing app bug, not env):**
  the SPA polls for status `started`/`processing`/`completed`, but the backend
  emits `queued`/`running`/`succeeded` (and chapter `done`). So the UI shows a
  job stuck on "Running" and never renders the download button even after the
  job succeeds. Verify synthesis end-to-end via the API
  (`POST /api/synthesize` then poll `GET /api/task/<id>` until `succeeded`) or
  the worker log — not the frontend UI.
