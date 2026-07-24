# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- runtime stage: static assets behind nginx, non-root ---
FROM nginx:1.27-alpine

# gettext provides envsubst for runtime variable substitution in nginx config.
RUN apk add --no-cache gettext

# Template (with ${BACKEND_PRIVATE_URL} placeholder) replaces the static config.
# The entrypoint substitutes the variable and writes the final default.conf.
RUN mkdir -p /etc/nginx/templates
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

COPY --from=build /app/dist /usr/share/nginx/html

# Run as the built-in non-root nginx user.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx \
                            /usr/share/nginx/html /etc/nginx/conf.d
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:8080/ >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
