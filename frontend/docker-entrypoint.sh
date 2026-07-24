#!/bin/sh
# Substitute runtime environment variables into the nginx config template,
# then hand off to the default nginx entrypoint.
#
# Required env vars:
#   BACKEND_PRIVATE_URL — private Railway URL of the backend service,
#                         e.g. http://backend.railway.internal:5000
set -e

: "${BACKEND_PRIVATE_URL:=http://localhost:5000}"

envsubst '${BACKEND_PRIVATE_URL}' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
