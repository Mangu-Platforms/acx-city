# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Deterministic install (blueprint rescue: no "npm ci || npm i" fallback).
RUN npm ci
COPY . .
RUN npm run build

# --- runtime stage: static assets behind nginx, non-root ---
FROM nginx:1.27-alpine
# nginx:alpine already ships an unprivileged config template on 8080.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Run as the built-in non-root nginx user.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:8080/ >/dev/null 2>&1 || exit 1
