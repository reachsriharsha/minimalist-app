# Design: Docker Compose stack and per-service Dockerfiles

## Approach

Introduce a minimal, dev-first docker-compose stack whose job is strictly **local orchestration** per `conventions.md` §8. Compose file, env template, and Makefile plumbing live in `infra/`; Dockerfiles live adjacent to the code they build (`backend/Dockerfile`, `frontend/Dockerfile`) because they are a property of the service, not of the orchestration.

Design principles driving the decisions below:

1. **One entrypoint script per service.** The Dockerfile `CMD`s invoke `backend/start.sh` and `frontend/start.sh`, the same scripts used for local non-Docker runs. Both scripts already carry top-of-file comments stating they will be reused as container entrypoints (`backend/start.sh:19`, `frontend/start.sh:20`). No shell logic is duplicated between "how I run this locally" and "how the container runs this."
2. **Dev by default.** `make up` (i.e. `docker compose up`) yields a hot-reload dev loop: backend uvicorn `--reload`, Vite dev server with HMR, source bind-mounted into containers. This is the most common path on a template repo and should be frictionless.
3. **Prod mode is opt-in and minimal.** A `prod` compose profile builds static frontend assets and serves them from `nginx:alpine`; backend runs uvicorn without `--reload`. No source bind mounts. This exists so the Dockerfiles are exercised against a production-shape build, and so a future deployment feature can reuse the Dockerfile targets unchanged.
4. **Database and cache are internal by default.** Postgres and Redis have no `ports:` stanza — they are reachable only over the compose network. Backend publishes 8000; frontend publishes 5173 (dev) or 8080 (prod, nginx). An operator who wants `psql` from the host can uncomment a line in `infra/.env` or use `docker compose exec postgres psql`.
5. **Migrations run on container start in dev.** The `MIGRATE=1` knob on `backend/start.sh` already exists; compose sets it in `infra/.env.example`. This is the right default for a template (clean clone → working DB in one command). For situations where that is wrong (e.g. pinning a specific revision while debugging), `make migrate` runs migrations as a one-shot and `MIGRATE` can be turned off in `infra/.env`.

### Open design calls surfaced for human review

Two choices are judgment calls allowed by the prompt; both are documented here and called out in the spec PR body so the human can veto:

- **Dev-by-default with opt-in `prod` profile**, rather than a separate `docker-compose.prod.yml` or a flag-driven split. Rationale: this is a template for local development; adding a second compose file doubles surface area for a path most users will never take. The `--profile prod` switch gives us a single source of truth with one additional keyword.
- **`MIGRATE=1` by default in `infra/.env.example`**, rather than requiring `make migrate` as a manual step. Rationale: the existing `backend/start.sh` already supports this cleanly; the first-run experience of "one command, working DB" outweighs the rare case where auto-migration surprises someone. The escape hatch (`make migrate`, plus toggling `MIGRATE=0`) is documented.

## Files to Create

| File | Purpose |
|---|---|
| `infra/docker-compose.yml` | Four-service stack (`backend`, `frontend`, `postgres`, `redis`), one user-defined network, named volumes for Postgres and Redis data, health checks, dev + `prod` profile. |
| `infra/.env.example` | Consolidated env for the compose stack: Postgres credentials, `DATABASE_URL` as seen from the backend container, `REDIS_URL`, published host ports, `VITE_API_BASE_URL`, `MIGRATE` flag, `ENV`. Copied to `infra/.env` (gitignored) on first run. |
| `infra/.gitignore` | Ignores `.env` and `.env.*` but **not** `.env.example`. |
| `backend/Dockerfile` | Multi-stage image for the FastAPI service: uv-based build stage, slim runtime stage, non-root user, `CMD ["./start.sh"]`. |
| `backend/.dockerignore` | Excludes `.venv/`, `.pytest_cache/`, `__pycache__/`, `*.pyc`, `.env`, `.env.*` (keeps `.env.example`), `tests/` from the runtime image but not the build context, etc. |
| `frontend/Dockerfile` | Multi-target image: `dev` target runs `bun run dev`; `prod` target builds via `bun run build` and serves from `nginx:alpine`. Both finals run as non-root. |
| `frontend/.dockerignore` | Excludes `node_modules/`, `dist/`, `.vite/`, `.env`, `.env.*` (keeps `.env.example`), etc. |
| `.dockerignore` (repo root) | Excludes `.git/`, `docs/`, `.claude/`, `backend/.venv`, `frontend/node_modules`, any `.env` files except `.env.example`, etc. Relevant when a build uses the repo root as context (not the default, but guarded anyway). |
| `Makefile` (repo root) | Developer-ergonomic forwarders: `up`, `down`, `logs`, `migrate`, `ps`, `build`, `clean`. Each target `cd`s into `infra/` and invokes `docker compose`. |

## Files to Modify

| File | Change Description |
|---|---|
| `README.md` (repo root) | Append a "Running with Docker" section documenting: prerequisites (Docker + Docker Compose v2), `cp infra/.env.example infra/.env`, `make up`, host-published ports (8000 backend, 5173 frontend dev), `make logs`, `make migrate`, `make down`, `make clean`, and a pointer to `infra/docker-compose.yml` as the source of truth. Existing content must remain byte-for-byte unchanged above the new section. Vulcan should add the section near the end of the file, below "Workflow" and above "License". |

## Compose Topology

Service graph:

```
 frontend  -->  backend  -->  postgres  (condition: service_healthy)
                       \-->  redis     (condition: service_healthy)
```

Network: one user-defined bridge network, e.g. `appnet`. Compose injects service-name DNS so `backend` reaches Postgres at `postgres:5432` and Redis at `redis:6379`.

### Service: `postgres`

- Image: `postgres:16-alpine` (version chosen to match the `postgresql+asyncpg://` driver that `backend/app/settings.py:34` defaults to; Vulcan may bump the minor at build time if 16 turns out to be problematic — document the chosen tag in `infra/.env.example`).
- Env: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` all sourced from `infra/.env`. Defaults in `.env.example`: `postgres` / `postgres` / `app` (matches `backend/app/settings.py:34` defaults so migrations "just work" out of the box).
- Volume: named volume `pgdata` mounted at `/var/lib/postgresql/data`.
- Health check: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` with a 5s interval, 5s timeout, 10 retries, 10s start period.
- Ports: **none published.** Internal only.

### Service: `redis`

- Image: `redis:7-alpine`.
- Volume: named volume `redisdata` mounted at `/data`. Config enables AOF persistence via the command line (e.g. `command: ["redis-server", "--appendonly", "yes"]`).
- Health check: `redis-cli ping` expecting `PONG` with a 5s interval, 3s timeout, 10 retries, 5s start period.
- Ports: **none published.** Internal only.

### Service: `backend`

- Build: `context: ..` (the repo root, so the build can see `backend/` without escaping upward), `dockerfile: ../backend/Dockerfile`. Alternatively `context: ../backend` with all paths relative to backend — Vulcan picks whichever keeps the Dockerfile simpler; design requires only that the choice be internally consistent.
- Env: loaded from `infra/.env`; maps to the backend's expected variables (`DATABASE_URL`, `REDIS_URL`, `HOST`, `PORT`, `LOG_LEVEL`, `MIGRATE`, `ENV`, `REQUEST_ID_HEADER`). The `DATABASE_URL` in `infra/.env.example` uses the compose hostname: `postgresql+asyncpg://postgres:postgres@postgres:5432/app`. Likewise `REDIS_URL=redis://redis:6379/0`.
- Ports: publishes container `8000` → host `${BACKEND_PORT:-8000}`.
- `depends_on`:
  ```yaml
  postgres: { condition: service_healthy }
  redis:    { condition: service_healthy }
  ```
- Dev mode (default): bind-mounts `../backend` → `/app` so code changes hot-reload via uvicorn's `--reload`. Startup runs `./start.sh serve --reload` (the compose `command:` overrides CMD in dev mode). When `MIGRATE=1` (default), `start.sh` runs `alembic upgrade head` before uvicorn.
- Prod profile (`profiles: ["prod"]` on an alternate `backend` command OR a second service `backend-prod`): no bind mount; runs `./start.sh serve` (no `--reload`).

### Service: `frontend`

- Build: `context: ..`, `dockerfile: ../frontend/Dockerfile`, `target: dev` (default) or `target: prod` under the `prod` profile.
- Env: `VITE_API_BASE_URL=http://localhost:${BACKEND_PORT:-8000}` from `infra/.env`. Because the Vite dev server runs inside the frontend container but the browser runs on the developer's host, the browser's idea of the backend is the host-published port, not the compose hostname — see "Data Flow" below.
- Ports: publishes container `5173` → host `${FRONTEND_PORT:-5173}` in dev; `8080` → host `${FRONTEND_PORT:-8080}` in prod (nginx).
- Dev mode: bind-mounts `../frontend` → `/app` with a named volume masking `/app/node_modules` so the container's installed `node_modules/` is not clobbered by the host bind mount. `CMD ["./start.sh", "dev"]`.
- `depends_on`: `backend` (condition: `service_started` is sufficient; frontend does not call backend at boot).

### Volumes

```yaml
volumes:
  pgdata:
  redisdata:
  frontend_node_modules:   # named volume masking /app/node_modules in the dev bind mount
```

### Network

```yaml
networks:
  appnet:
```

All four services are attached to `appnet`. No custom driver or subnet — the default bridge is sufficient.

## Dockerfile Stages

### `backend/Dockerfile`

Two stages:

1. **`builder`** (based on `python:3.12-slim` or `python:3.11-slim` to match `requires-python = ">=3.11"` in `backend/pyproject.toml:6`):
   - Install `uv` (pin a version; document in a comment).
   - Copy `pyproject.toml`, `uv.lock` first to maximize Docker layer cache on dependency changes.
   - `uv sync --frozen --no-install-project` to install dependencies.
   - Copy the rest of `backend/`.
   - `uv sync --frozen` to install the project itself.
2. **`runtime`** (same slim base):
   - Create a non-root user (`appuser`, uid 1000).
   - Copy the `.venv` from `builder` and the app source.
   - `WORKDIR /app`.
   - `USER appuser`.
   - `EXPOSE 8000`.
   - `ENTRYPOINT ["./start.sh"]` and `CMD ["serve"]`. The entrypoint/CMD split lets `make migrate` override with `["migrate"]` via compose `command:`.

### `frontend/Dockerfile`

Three stages:

1. **`base`** (based on `oven/bun:1` or `node:20-alpine` + `bun` — Vulcan picks the simpler option; document the choice with a one-line comment). Installs OS deps needed by Vite if any, copies `package.json` and `bun.lock`, runs `bun install --frozen-lockfile`.
2. **`dev`** (default target for dev mode): copies the rest of `frontend/`, creates a non-root user, `USER appuser`, `EXPOSE 5173`, `CMD ["./start.sh", "dev"]`.
3. **`build`**: reuses `base`, copies source, runs `bun run build` to produce `dist/`.
4. **`prod`**: based on `nginx:alpine`, copies the `dist/` output from the `build` stage, uses a tiny default nginx config that serves `/` as SPA (try_files with fallback to `index.html`), exposes `8080`, runs as the stock nginx non-root variant (`nginx:alpine` already includes `nginx-unprivileged`-style defaults; Vulcan confirms at build time).

## Data Flow

From a developer's host, after `make up`:

```
browser (host)
   │  GET http://localhost:5173
   ▼
frontend container  (Vite dev server on :5173, source bind-mounted)
   │  (Vite's proxy or direct fetch; see note below)
   ▼
browser (host)  ── GET http://localhost:8000/api/v1/hello ──▶  backend container (:8000)
                                                                  │
                                                                  ├── SELECT 1 ──▶  postgres (:5432, internal only)
                                                                  └── PING     ──▶  redis    (:6379, internal only)
```

Note on the Vite proxy: `frontend/vite.config.ts` already proxies `/api` to `VITE_API_BASE_URL`. In compose, we set `VITE_API_BASE_URL=http://backend:8000` if the proxy runs inside the container (server-side), **but** if the frontend code calls the backend directly from the browser, the URL must be the host-published address (`http://localhost:8000`). The current frontend (`feat_frontend_001`) relies on Vite's dev-server proxy for `/api` — so the proxy target can be `http://backend:8000` (server-side resolution inside the frontend container) and the browser only ever hits `http://localhost:5173/api/...`. Vulcan must confirm this by reading `frontend/src/api/client.ts` at build time; if the client uses an absolute URL, the env var must point at the host-published backend instead. This is the single subtle wiring decision in the whole feature — call it out in the build PR.

For migrations:

```
make migrate
   │  docker compose run --rm backend ./start.sh migrate
   ▼
backend container  ── alembic upgrade head ──▶  postgres
```

## Env var flow

Single source of truth: `infra/.env` (copied from `infra/.env.example`).

`infra/docker-compose.yml` declares `env_file: .env` under each service and additionally uses `${VAR}` interpolation for values that appear in `ports:` or compose-level config. This means:

- **Stack-shape vars** (host port mappings, Postgres credentials used by the `postgres` service init, image tags) — come from `${VAR}` interpolation at compose parse time.
- **Runtime vars** (consumed by the app processes: `DATABASE_URL`, `REDIS_URL`, `LOG_LEVEL`, etc.) — come from `env_file:` and land in the container environment, where pydantic-settings in `backend/app/settings.py` picks them up.

`infra/.env.example` documents every variable with a comment. Backend's own `backend/.env.example` is retained (it works for non-Docker local runs) but the compose flow does not read it; the two templates may drift intentionally (e.g. `DATABASE_URL` points at `localhost` in `backend/.env.example`, at `postgres` in `infra/.env.example`).

Proposed `infra/.env.example` keys (non-exhaustive):

```
# Host-published ports
BACKEND_PORT=8000
FRONTEND_PORT=5173

# Postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=app

# Backend runtime
ENV=dev
LOG_LEVEL=INFO
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/app
REDIS_URL=redis://redis:6379/0
MIGRATE=1
REQUEST_ID_HEADER=X-Request-ID

# Frontend runtime
VITE_API_BASE_URL=http://backend:8000
```

## Health check design

- **postgres** — `pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB`. The double `$$` escapes compose variable interpolation so the shell inside the container resolves it. Interval 5s, retries 10, start_period 10s. This is well-established Docker idiom; the reason we're being explicit is so `backend` can `depends_on: { condition: service_healthy }` without flakiness on slow laptops.
- **redis** — `redis-cli ping` matched against `PONG`. Interval 5s, retries 10, start_period 5s.
- **backend** — a compose-level health check is **not** required for this feature (no other service waits on backend's readiness). The application exposes `GET /readyz` (`backend/app/api/health.py:24`) which is used by humans and by `feat_testing_001` validation, not by compose itself. Optional polish: we could add `healthcheck: curl -fsS http://localhost:8000/readyz` using `curl` if it's in the slim image, or use Python + urllib to avoid installing curl. Vulcan may add this if it's a one-liner; it's not a blocker.
- **frontend** — no health check. Readiness is "Vite printed its bind line" which is hard to express portably; `depends_on: backend` on downstream services (there are none today) is enough.

## Makefile targets

Root `Makefile`, intentionally small (< 40 lines of non-comment content). Every target is a thin forwarder:

| Target | Behavior |
|---|---|
| `make up` | `cd infra && docker compose up -d --build` (dev profile). Exits after services report healthy on their own (compose handles this). |
| `make down` | `cd infra && docker compose down`. Containers and network go; named volumes stay. Idempotent. |
| `make logs` | `cd infra && docker compose logs -f`. |
| `make ps` | `cd infra && docker compose ps`. |
| `make build` | `cd infra && docker compose build`. Rebuilds images without starting services. |
| `make migrate` | `cd infra && docker compose run --rm backend ./start.sh migrate`. One-shot. |
| `make clean` | `cd infra && docker compose down -v`. Named volumes removed. Destructive. Print a confirmation-prompting `@echo` header so this is not accidentally invoked by muscle memory; interactive `read` is overkill for a template. |
| `make help` (default) | Prints the target list with one-line descriptions. |

A mirror `Makefile` inside `infra/` is **not** planned unless Vulcan finds that some target genuinely reads more clearly there; per prompt, that's optional and should only land if it simplifies something.

## Migration Strategy (recap)

- Dev (default): `MIGRATE=1` in `infra/.env.example` → `backend/start.sh` runs `alembic upgrade head` before uvicorn. No code change on backend side — already supported by `backend/start.sh:52`.
- Escape hatch: `make migrate` → `docker compose run --rm backend ./start.sh migrate`. Useful when `MIGRATE=0` is set locally for debugging, or when the operator wants an explicit migration step in a script.
- Prod profile: Vulcan should leave `MIGRATE=1` on in the prod profile too unless there is a concrete reason not to; this is a template, not a prod deployment pipeline, and hardening is `deployment/`'s job.

## Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| Host bind mount of `frontend/` masks the container's `node_modules/`, breaking `bun run dev`. | Declare a named volume `frontend_node_modules` mounted at `/app/node_modules` in the dev profile so the container-local install is preserved. |
| Backend container starts before Postgres is actually accepting connections (TCP up but not ready). | `postgres` health check is `pg_isready`, not a TCP probe. Backend uses `depends_on: { condition: service_healthy }`. |
| `MIGRATE=1` on every container restart slows down the dev loop. | Alembic no-ops if the DB is already at head, so the cost is a single `SELECT` per restart. Operators who mind can set `MIGRATE=0`. |
| Vite dev server inside a container does not reach the host browser because HMR websocket is misconfigured. | Vite's default `server.host` is `localhost`; the `frontend/start.sh dev` entrypoint forwards `--host 0.0.0.0` (see `frontend/start.sh:53`). No extra config needed, but Vulcan must verify by hitting `http://localhost:5173` from the host browser during manual validation. |
| Frontend code uses absolute backend URLs (not the `/api` prefix + proxy), so the `VITE_API_BASE_URL=http://backend:8000` value does not work for the browser. | Read `frontend/src/api/client.ts` at build time. If absolute URLs are in use, switch `infra/.env.example` to `VITE_API_BASE_URL=http://localhost:8000` and accept that the browser, not the container, is the caller. Flag the choice in the build PR. |
| Ports 5432 or 6379 accidentally published, exposing unauthenticated DB to the network. | Compose has no `ports:` stanza on `postgres` or `redis`. `infra/.env.example` does not define `POSTGRES_PORT` / `REDIS_PORT` host mapping vars. To expose, an operator must hand-edit compose, which is a deliberate act. |
| `deployment/` silently appears in this feature. | Acceptance criterion gates on this, and the review checklist in the spec PR body should include "confirm `deployment/` not created". |
| Image bloat (hundreds of MB). | `-slim` / `-alpine` bases; multi-stage build discards build tooling; `.dockerignore` trims context. Not a blocker for this feature; a later feature can tune further. |
| `make clean` destroys data unexpectedly. | Target prints a clear `@echo` warning line before running `docker compose down -v`. No interactive confirm (template repo; users who type `make clean` deserve to be believed). |
| Docker Compose v1 (`docker-compose` with a hyphen) vs v2 (`docker compose`). | Makefile and README standardize on v2 syntax (`docker compose`). README "Running with Docker" lists Docker Desktop 4.x / Docker Engine 20.10+ as the prerequisite so v2 is guaranteed. |
| Alembic migrations race when multiple backend replicas start simultaneously. | N/A for this feature — compose runs one `backend` replica. Future deployment work owns multi-replica migration strategy. |

## Dependencies

External (pulled at image build / compose-up time, **not** committed):

- `python:3.11-slim` or `python:3.12-slim` (Docker Hub)
- `postgres:16-alpine` (Docker Hub)
- `redis:7-alpine` (Docker Hub)
- `oven/bun:1` or `node:20-alpine` + `bun` — Vulcan's call, documented inline
- `nginx:alpine` (prod profile only)
- `uv` (installed into the backend builder stage; version pinned in the Dockerfile)

No Python or Node packages added. No backend or frontend source changes. No new runtime services.
