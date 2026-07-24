#!/usr/bin/env sh
set -e

# Wait briefly for the database, then apply migrations before starting.
# Both the API and the worker containers use this entrypoint; only the API
# runs migrations (ROLE=api) so they aren't applied twice concurrently.

if [ "${ROLE:-api}" = "api" ]; then
  echo "[entrypoint] applying database migrations..."
  alembic upgrade head
fi

echo "[entrypoint] starting role=${ROLE:-api}"
exec "$@"
