#!/usr/bin/env bash
# Run the API and the job worker together in one container.
#
# Railway mounts a volume to exactly one service, but the API and worker must
# share /data (the worker writes audio outputs, the API serves the downloads).
# So on Railway both processes run in this single combined service.
# See RAILWAY_SETUP.md — a split topology requires STORAGE_BACKEND=s3.
set -uo pipefail

python worker.py &
gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 2 --threads 4 --timeout 3600 wsgi:app &

# If either process dies, exit so the platform restarts the whole service.
wait -n
exit $?
