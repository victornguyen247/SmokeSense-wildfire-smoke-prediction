# syntax=docker/dockerfile:1
# Production frontend image for staging: build once, serve static files with nginx.
# (frontend.Dockerfile stays as the dev-server image used by docker-compose.)
#
# VITE_API_BASE_URL is baked in at build time. Staging serves the API from the SAME
# origin (Caddy routes /api/* to the backend), so the default is empty and the app
# falls back to window.location.origin (frontend/src/constants/env.ts).

FROM node:22-slim AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html

# SPA fallback so client-side routes survive a page refresh. Vite fingerprints /assets/*,
# so those cache forever; index.html must always be revalidated or a deploy never shows up.
RUN <<'EOF'
cat > /etc/nginx/conf.d/default.conf <<'CONF'
server {
  listen 80;
  root /usr/share/nginx/html;

  location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
    try_files $uri =404;
  }

  location / {
    add_header Cache-Control "no-cache";
    try_files $uri $uri/ /index.html;
  }
}
CONF
EOF

EXPOSE 80
