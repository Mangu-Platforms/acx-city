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

## Cloud/sandbox dev environment notes

These caveats apply to any hosted agent VM (Cursor Cloud, CI sandboxes, etc.)
with **no Docker and no PostgreSQL** — develop against SQLite;
`docker-compose.yml` / `railway.toml` are deploy-only.

Standard lint/test/build/run commands live in `README.md` and
`agent-skills/acx-city/SKILL.md` (Verification section). Non-obvious caveats:

- **Backend DB (SQLite):** an unset or empty `DATABASE_URL` falls back to
  `sqlite:///./audiobook.db` in dev (in production an empty value is a hard
  error — it means a broken Railway reference variable). For local dev copy
  `.env.example` to `backend/.env` and set a non-empty `JWT_SECRET`. Then run
  `alembic upgrade head` once (from `backend/`, venv active) to create the
  schema before starting the API/worker. The Postgres-only
  `FOR UPDATE SKIP LOCKED` test auto-skips on SQLite (expect `1 skipped` in
  pytest).
- **Run the app (dev):** with `backend/.venv` active, `python app.py` (API on
  `:5000`), `python worker.py` (job worker, second terminal). `frontend`:
  `npm run dev` (`:5173`, proxies `/api` to `:5000`). `dashboard`:
  `npm run dev` (`:3000`) and requires `NEXT_PUBLIC_API_URL=http://localhost:5000`
  (put it in `dashboard/.env.local`). The worker is a separate process — the API
  only enqueues jobs, so nothing synthesizes unless `worker.py` is running.
- **edge-tts:** the default free TTS provider talks to Microsoft over a
  WebSocket. Older pins (`6.1.12`) get a `403 Invalid response status` and every
  job fails "chunk synthesis failed after 3 attempts"; the pinned `edge-tts`
  (7.x) works. Requires outbound egress.
- **Job status vocabulary:** the backend emits `queued`/`running`/`succeeded`
  (chapters: `done`). The SPA accepts these plus the older
  `started`/`processing`/`completed` names (fixed on main — an earlier bug
  showed jobs stuck on "Running"). When verifying synthesis end-to-end without
  a browser, poll the API directly: `POST /api/synthesize`, then
  `GET /api/task/<id>` until `succeeded`.
