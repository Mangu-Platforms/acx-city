#!/bin/sh
# Substitute runtime environment variables into the nginx config template,
# then hand off to the default nginx entrypoint.
#
# Required env vars:
#   BACKEND_PRIVATE_URL — private Railway URL of the backend service,
#                         e.g. http://backend.railway.internal:5000
#   PORT                — port nginx listens on. Railway injects this; defaults
#                         to 8080 for local/compose use.
set -e

: "${BACKEND_PRIVATE_URL:=http://localhost:5000}"
: "${PORT:=8080}"

# Only substitute our known variables so nginx's own $-vars are left intact.
envsubst '${BACKEND_PRIVATE_URL} ${PORT}' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
