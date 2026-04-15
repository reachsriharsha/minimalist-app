# Feature: Docker Compose stack and per-service Dockerfiles

## Problem Statement

`feat_backend_001` and `feat_frontend_001` each produce working services, but running the full template today requires four manual terminals: start Postgres, start Redis, run `backend/start.sh`, run `frontend/start.sh`. There is no reproducible way for someone who just cloned this template to bring the whole stack up, and no containerized build that a future deployment feature (DigitalOcean, AWS, Azure, etc.) can reuse.

This feature introduces the local orchestration layer promised by `conventions.md` §8 (the `infra/` directory) and §10 (feature 4 of 5 in the bootstrap roster): a `docker-compose.yml` that stands up `backend`, `frontend`, `postgres`, and `redis` together, a per-service `Dockerfile` for the two application services, a small root `Makefile` with ergonomic shortcuts, and a consolidated `infra/.env.example` so a new contributor can get from clean clone to running stack in one command.

Deployment artifacts (Helm, Terraform, cloud-specific scripts) are **not** part of this feature. Per `conventions.md` §8, `deployment/` is introduced by a later infra feature; this feature owns local orchestration only.

## Requirements

- A new `infra/` directory at the repo root containing:
  - `infra/docker-compose.yml` — defines four services (`backend`, `frontend`, `postgres`, `redis`), a shared network, and named volumes for Postgres and Redis data.
  - `infra/.env.example` — a single consolidated env template for the compose stack, committed (the real `.env` is gitignored).
- A `backend/Dockerfile` adjacent to backend code (per user decision, not inside `infra/`).
- A `frontend/Dockerfile` adjacent to frontend code (per user decision, not inside `infra/`).
- A `.dockerignore` at the repo root, and per-service `.dockerignore` files under `backend/` and `frontend/`, so build contexts stay small and do not leak secrets or build artifacts.
- A root `Makefile` with developer-ergonomic targets (`make up`, `make down`, `make logs`, `make migrate`, `make ps`, `make build`, `make clean`) that forward into `infra/` so the compose file can live there without forcing every command to `cd infra`.
- The stack defaults to **dev mode** (bind-mounted source, backend uvicorn `--reload`, Vite dev server with HMR). A minimal `prod` profile builds static frontend assets behind nginx and runs uvicorn without reload; it is opt-in via `docker compose --profile prod up`.
- Postgres and Redis expose health checks so `backend` can `depends_on: condition: service_healthy` and `make up` does not race.
- A new "Running with Docker" section is **appended** to the root `README.md` (existing content stays intact) documenting the `make up` path from clean clone.

## User Stories

- As a developer cloning this template, I want to run `cp infra/.env.example infra/.env && make up` from the repo root and have the full stack (frontend, backend, Postgres, Redis) come up healthy in one command, so I can start working on features immediately without rediscovering service wiring.
- As the author of `feat_testing_001`, I want a reliable `make up` that yields healthy services at known ports, so the REST functional suite can target `http://localhost:8000` (or the compose-exposed port) without starting services by hand.
- As the author of a future deployment feature, I want per-service Dockerfiles that already build a production-suitable image (multi-stage, non-root, slim base), so `deployment/` only has to orchestrate and configure — not re-define — the runtime image.
- As an operator running this template in a shared environment, I want Postgres and Redis to be reachable only on the compose network by default (not published to the host), so a development laptop does not accidentally expose an unauthenticated database.

## Scope

### In Scope

- `infra/docker-compose.yml` with services `backend`, `frontend`, `postgres`, `redis`; named volumes for Postgres and Redis data; a shared user-defined network.
- Health checks on `postgres` and `redis`; `backend` waits for both to be healthy before starting.
- `backend/Dockerfile` — multi-stage (uv-based build stage, slim runtime stage), non-root user, uses `backend/start.sh` as the `CMD` entrypoint so local and containerized runs share one script (per the comment block at the top of `backend/start.sh`).
- `frontend/Dockerfile` — dual-target:
  - default (dev) stage runs `bun run dev` with bind-mounted source for HMR;
  - `prod` stage builds static assets via `bun run build` and serves them from `nginx:alpine`.
  - Both stages run as a non-root user in the final image.
- `infra/.env.example` — consolidated env for the stack: Postgres credentials, DB URL as seen from the backend container, Redis URL, published host ports, `VITE_API_BASE_URL`, `MIGRATE` flag. The real `infra/.env` is gitignored.
- `.dockerignore` at repo root, `backend/.dockerignore`, `frontend/.dockerignore`.
- Root `Makefile` with targets documented in the design spec.
- Append a "Running with Docker" section to the root `README.md` covering the one-command bring-up and tear-down, and listing the host-published ports.
- Migration strategy: the backend container runs `alembic upgrade head` at startup when `MIGRATE=1` is set in `infra/.env` (the default in the committed `.env.example`). A `make migrate` target is also provided as a one-shot escape hatch. Leverages existing `MIGRATE=1` / `migrate` support in `backend/start.sh` — no backend source changes.

### Out of Scope

- `deployment/` directory and its contents. The user will add deployment scripts for DigitalOcean, AWS, and Azure in later features. This feature does **not** create `deployment/` even as a placeholder.
- CI/CD (GitHub Actions, image publishing, registry auth). Deferred per `conventions.md` §11.
- TLS termination, reverse proxies beyond the single `nginx:alpine` that serves frontend static assets under the `prod` profile, and any form of certificate management.
- Secrets management (Vault, SOPS, Doppler, cloud KMS). Env vars come from `infra/.env` only.
- Kubernetes manifests, Helm charts, Terraform, Pulumi, or any other IaC.
- Automated tests for this feature. Validation is manual, documented in the test spec. Automated functional testing against this stack is `feat_testing_001`'s job.
- Linting, formatting, or dev-tooling containers.
- Changes to `backend/` or `frontend/` source code. The Dockerfiles must work with the services as they exist on `main` today; any needed behavior is already present in `backend/start.sh` and `frontend/start.sh`.
- Changes to `docs/tracking/features.md` (tracking file is currently neutered).

## Acceptance Criteria

- [ ] `infra/docker-compose.yml` exists and declares exactly four services: `backend`, `frontend`, `postgres`, `redis`.
- [ ] `infra/.env.example` exists and is sufficient, when copied to `infra/.env` with no edits, to bring the stack up on a clean machine.
- [ ] `backend/Dockerfile` exists, is multi-stage, uses a slim Python base, runs as a non-root user in the runtime stage, and uses `backend/start.sh` as the entrypoint.
- [ ] `frontend/Dockerfile` exists, is multi-stage, supports both a dev target (runs `bun run dev`) and a `prod` target (serves built assets from `nginx:alpine`), and runs as a non-root user in the final stage of both targets.
- [ ] `.dockerignore` files exist at repo root, `backend/`, and `frontend/`, and they exclude at minimum: `.git`, `node_modules`, `.venv`, `__pycache__`, `dist/`, `.env`, `.env.*` (but not `.env.example`).
- [ ] A root `Makefile` exists and implements `up`, `down`, `logs`, `migrate`, `ps`, `build`, `clean` targets that forward into the compose stack.
- [ ] Postgres and Redis both declare health checks in compose; `backend` declares `depends_on` with `condition: service_healthy` on both.
- [ ] Postgres and Redis do **not** publish ports to the host by default. Backend publishes port 8000; frontend publishes its dev server port (5173 by default).
- [ ] Named volumes (e.g. `pgdata`, `redisdata`) are declared for Postgres and Redis persistence; destroying containers does not lose data unless `make clean` is invoked.
- [ ] From a clean clone, running `cp infra/.env.example infra/.env && make up` brings all four services to healthy state without manual intervention.
- [ ] With the stack up, `curl -fsS http://localhost:8000/readyz` returns HTTP 200 and a body with `"status": "ready"` and both `db` and `redis` reported as `"ok"`.
- [ ] With the stack up, the frontend served at the published port successfully fetches `/api/v1/hello` through the compose network (no CORS surprises, no connection-refused).
- [ ] `make down` stops the stack cleanly; running it twice is idempotent.
- [ ] `make clean` removes containers **and** named volumes; a subsequent `make up` starts from a fresh database.
- [ ] The root `README.md` contains a new "Running with Docker" section (appended; existing content intact).
- [ ] No files under `backend/app/` or `frontend/src/` are modified.
- [ ] `deployment/` is **not** created by this feature.
- [ ] All commits on the branch use the prefix `autodev(feat_infra_001):` per `conventions.md` §4.
