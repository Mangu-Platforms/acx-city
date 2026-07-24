# Revamp changes — repository rescue phase

This maps every action to the blueprint's **Appendix C cleanup checklist** and
**"First 72 hours: repository rescue"** section. Each row: what was done and how
it's verified.

| Blueprint item | Done | Verification |
| --- | --- | --- |
| Move `frontend/public/index.html` → `frontend/index.html` | ✅ | `frontend/index.html` is the Vite entry; `npm run build` succeeds from a clean checkout |
| Move `ci-cd/github-actions.yml` → `.github/workflows/ci.yml` | ✅ | GitHub-recognized workflow path |
| Remove `.DS_Store`, `__pycache__`, `.pytest_cache`, `uploads`, `outputs`, `cache` from source | ✅ | Only source + `.gitkeep` placeholders remain |
| Add `.gitignore` / `.dockerignore` | ✅ | Root + `backend/` + `frontend/` variants; generated/private files blocked |
| Commit `package-lock.json` | ✅ | `frontend/package-lock.json` present; `npm ci` runs deterministically |
| Use `VITE_API_BASE_URL` or same-origin `/api` | ✅ | `frontend/src/services/api.ts`; no hardcoded host; dev proxy in `vite.config.ts` |
| Replace `npm ci \|\| npm i` with deterministic `npm ci` | ✅ | CI and frontend Dockerfile use `npm ci` only |
| Replace Python/Vite dev serving (production process model) | ✅ | Backend runs `gunicorn wsgi:app`; frontend served static by nginx |
| Add upload server allowlist / MIME verification | ✅ | `/api/upload` rejects non-`.txt/.pdf/.docx` (extension + MIME), returns 415 |
| Reduce / scope CORS | ✅ | Defaults to `http://localhost:5173`, not `*` |
| Harden containers (non-root, health, signal policy) | ✅ | Both Dockerfiles: non-root user, `HEALTHCHECK`; backend uses `tini` as init |
| Persist outputs/cache appropriately | ✅ | Storage paths are env-configurable; compose mounts a named volume at `/data` |
| Add Ruff / Python type-check + ESLint/Prettier baseline; run in CI | ✅ | `backend/pyproject.toml` (ruff), `frontend/.eslintrc.cjs`, `.prettierrc.json`; CI runs lint + tests + build |
| Document supported file types and reject others on the server | ✅ | Allowlist in `app.py`; README documents behavior |
| Publish an honest current-state README | ✅ | `README.md` labels prototype limitations and links the blueprint |

## Items intentionally deferred (foundation phase, not rescue)

These blueprint items require real feature work and were **not** part of this
repository-rescue pass. They're documented in the README's "Known limitations":

- **Persist/replace `active_tasks`** (durable, restart-safe jobs — PostgreSQL).
- **Add auth and ownership** (a task ID should not authorize access).
- **Add retry/cancel/queue limits** for safe external-provider execution.
- **Replace `print` with structured logging.**

## Verification performed

- `pytest -q` → **8 passed** (backend).
- `ruff check .` → **All checks passed** (backend baseline).
- `tsc --noEmit` → **pass**; `npm run build` → **built successfully** (frontend).
- `npm run lint` (ESLint) → **exit 0**.
- Confirmed the built bundle contains **no hardcoded `localhost:5000`** backend URL.
