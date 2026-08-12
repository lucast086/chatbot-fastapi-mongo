# syntax=docker/dockerfile:1
#
# Build the SPA, then serve it from nginx with /api proxied to the backend.
# One origin means no CORS configuration and one URL to hand a reviewer.

# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Manifest and lock only, so this layer survives edits to the source.
COPY package.json package-lock.json ./
# `npm ci`, not `npm install`: it installs exactly what the lock file says and
# fails if the two have drifted, instead of quietly resolving something else.
RUN npm ci

COPY . .
RUN npm run build


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------
FROM nginx:1.29-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
