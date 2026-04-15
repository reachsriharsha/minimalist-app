# frontend/Dockerfile
#
# Multi-stage / multi-target image for the Vite + React + TS frontend.
#
#   deps    -- installs bun dependencies against the committed lockfile
#   dev     -- runs `bun run dev` (Vite) with HMR; source is bind-mounted in compose
#   build   -- runs `bun run build` to produce dist/
#   prod    -- nginx:alpine serving the built dist/ as an SPA
#
# Using `oven/bun:1` as the base: it's the upstream-maintained image that
# ships a working `bun` CLI and a Debian slim userspace compatible with
# Vite's native deps (vs. mixing `node:20-alpine` + a hand-installed bun).
#
# Build contexts:
#   - Compose invokes this with `context: ..` (repo root) and
#     `dockerfile: frontend/Dockerfile`, so paths below are relative to the
#     repo root.

# -----------------------------------------------------------------------------
# Stage: deps
# -----------------------------------------------------------------------------
FROM oven/bun:1 AS deps

WORKDIR /app

# Copy only manifests first for layer-cache reuse.
COPY frontend/package.json frontend/bun.lock ./

RUN bun install --frozen-lockfile

# -----------------------------------------------------------------------------
# Stage: dev
# -----------------------------------------------------------------------------
# The dev target runs the Vite dev server. Compose bind-mounts the host
# `frontend/` dir over `/app` and uses a named volume to preserve
# `/app/node_modules` installed above.
FROM oven/bun:1 AS dev

ENV NODE_ENV=development

WORKDIR /app

# Re-create the non-root user. oven/bun:1 ships with a `bun` user (uid 1000);
# we reuse it rather than creating a new one.
RUN chown -R bun:bun /app

# Bring in installed node_modules from the deps stage so a first `make up`
# works before the bind mount's node_modules volume is populated.
COPY --from=deps --chown=bun:bun /app/node_modules /app/node_modules

# Copy the rest of the frontend source. Under compose dev mode this is masked
# by a bind mount, but the image is still usable standalone.
COPY --chown=bun:bun frontend/ /app/

USER bun

EXPOSE 5173

ENTRYPOINT ["./start.sh"]
CMD ["dev"]

# -----------------------------------------------------------------------------
# Stage: build
# -----------------------------------------------------------------------------
FROM oven/bun:1 AS build

ENV NODE_ENV=production

WORKDIR /app

COPY --from=deps /app/node_modules /app/node_modules
COPY frontend/ /app/

# VITE_API_BASE_URL is baked into the bundle at build time when used. The
# frontend uses relative `/api/...` URLs via the Vite dev proxy, so the value
# here does not affect prod correctness when nginx serves the static bundle
# behind a reverse proxy. For the bundled prod profile we leave the env var
# unset here; nginx routes `/api/*` to the backend service (see prod stage).
RUN bun run build

# -----------------------------------------------------------------------------
# Stage: prod
# -----------------------------------------------------------------------------
# Serves the built SPA from nginx:alpine. The image ships the official
# `nginx` user (non-root worker processes by default under `user nginx;`).
FROM nginx:alpine AS prod

# SPA-aware nginx config: try_files with fallback to /index.html so client
# routes don't 404, and proxy /api/ to the backend service on the compose
# network so the browser can use relative URLs.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# nginx:alpine already runs master as root and workers as `nginx`; upstream's
# entrypoint handles signal forwarding. No CMD override needed.
