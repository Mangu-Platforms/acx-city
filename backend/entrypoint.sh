#!/usr/bin/env sh
set -e

# Wait briefly for the database, then apply migrations before starting.
# Both the API and the worker containers use this entrypoint; only the API
# runs migrations (ROLE=api) so they aren't applied twice concurrently.

if [ "${ROLE:-api}" = "api" ]; then
  echo "[entrypoint] applying database migrations..."
  alembic upgrade head

  # Seed stock voices on first run (idempotent — skips existing entries)
  if [ "${SEED_VOICES:-true}" = "true" ]; then
    echo "[entrypoint] seeding stock voices catalog..."
    python -m scripts.seed_voices || echo "[entrypoint] voice seeding skipped (non-fatal)"
  fi
fi

echo "[entrypoint] starting role=${ROLE:-api}"
exec "$@"
