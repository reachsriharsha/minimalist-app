# Test Spec: Docker Compose stack and per-service Dockerfiles

## Scope of this test spec

This feature ships infrastructure (Dockerfiles, compose file, Makefile, env template), not application code. There are **no automated tests added by this feature**. Validation is manual, performed by Vulcan after implementation and by the human reviewer before merging.

The automated REST functional suite that exercises running services (including services brought up via this compose stack) is owned by **`feat_testing_001`** — the next and final bootstrap feature. That feature will consume the `make up` contract defined here.

Everything below is a manual validation checklist. Each case lists the command to run, the input/state it assumes, and the pass criteria.

## Preconditions

Before running any case:

- Working tree is clean on `main` with `feat_infra_001` merged (for pre-merge validation: on the build branch).
- Docker Engine 20.10+ / Docker Desktop 4.x or newer, providing `docker compose` (v2) is installed and running.
- No other process is bound to host ports 8000 or 5173.
- Run once: `cp infra/.env.example infra/.env`. Do not edit the file for the default-path cases.

## Happy Path

| # | Test Case | Input / Action | Expected Output |
|---|---|---|---|
| 1 | Clean-clone bring-up | From repo root: `cp infra/.env.example infra/.env && make up` | All four services (`backend`, `frontend`, `postgres`, `redis`) reach state `running` and, where applicable, `healthy`. `docker compose ps` (via `make ps`) shows no `Exit` or `Restarting` statuses. Command returns to the shell after compose reports healthy. |
| 2 | Backend readiness through compose network | With the stack up from case 1: `curl -fsS http://localhost:8000/readyz` | HTTP 200. JSON body contains `"status": "ready"`, `"checks": {"db": "ok", "redis": "ok"}`. |
| 3 | Backend liveness | `curl -fsS http://localhost:8000/healthz` | HTTP 200. JSON body contains `"status": "ok"`. |
| 4 | Backend API reachable directly from host | `curl -fsS http://localhost:8000/api/v1/hello` | HTTP 200. JSON body contains the `message`, `item_name`, `hello_count` fields defined by `feat_backend_001`. |
| 5 | Frontend served from host-published port | `curl -fsS -I http://localhost:5173/` | HTTP 200 (or 304). `content-type` is `text/html`. |
| 6 | Frontend reaches backend through the compose network | In a browser: open `http://localhost:5173/`. | Page renders the `/api/v1/hello` payload (at least the `message` field is visible). No connection-refused or CORS error in the browser devtools console. |
| 7 | Migrations ran automatically on first boot | `docker compose -f infra/docker-compose.yml exec postgres psql -U postgres -d app -c "SELECT version_num FROM alembic_version;"` (or `docker compose exec` from `infra/`) | Exactly one row; `version_num` is the head revision committed under `backend/alembic/versions/`. |
| 8 | Hot reload in dev mode (backend) | With the stack up, edit any handler file under `backend/app/` (e.g. add a log line to `app/main.py`). Save. | Backend container logs show uvicorn reloading within ~2s. Subsequent request reflects the change without `make down`/`make up`. Revert the edit afterward. |
| 9 | Hot reload in dev mode (frontend) | With the stack up, edit the page component under `frontend/src/`. Save. | Browser at `http://localhost:5173/` reflects the change via HMR without a manual refresh. Revert the edit afterward. |
| 10 | Clean teardown | `make down` | All four service containers stop and are removed. Named volumes `pgdata`, `redisdata`, `frontend_node_modules` still exist (`docker volume ls` shows them). |
| 11 | Teardown is idempotent | `make down` a second time | Exit status 0. No "not found" errors. |
| 12 | Data persists across restart | From a freshly-torn-down state (case 10): `make up` again | Case 7 (alembic_version row) still passes; no duplicate migration was applied. |
| 13 | Destructive clean removes volumes | `make clean` | Containers and network gone; `docker volume ls` no longer lists `pgdata`, `redisdata`, `frontend_node_modules` (at minimum the ones this stack owns). |
| 14 | Clean-cycle-up after `make clean` | Immediately after case 13: `make up` | Stack comes up healthy; `alembic_version` shows the head revision again (migrations re-ran against a fresh database). No data from the previous run survives. |
| 15 | Explicit one-shot migration works | With `MIGRATE=0` in `infra/.env`, from clean state: `make up` followed by `make migrate` | `make up` brings Postgres healthy and starts backend without running migrations (backend logs show no "running alembic upgrade head" line from `backend/start.sh`). `make migrate` exits 0 and leaves `alembic_version` populated to head. Restore `MIGRATE=1` in `infra/.env` afterward. |

## Error Cases

| # | Test Case | Input / State | Expected Behavior |
|---|---|---|---|
| 1 | `infra/.env` missing | Delete `infra/.env`, then `make up` | Compose fails with a clear message naming the missing file (compose's own error). No containers are left in a partial state. |
| 2 | Backend fails to start because DB URL points nowhere | Edit `infra/.env`: set `DATABASE_URL=postgresql+asyncpg://postgres:postgres@does-not-exist:5432/app`. `make down && make up`. | Backend container enters a retry/error state. `curl http://localhost:8000/readyz` returns HTTP 503 with `"status": "not_ready"` and a populated `checks.db` error string (matches the error-path in `backend/app/api/health.py:32-38`). Fix: restore `.env`. |
| 3 | Postgres health never goes healthy | Edit `infra/.env`: set `POSTGRES_PASSWORD=` (empty). `make down && make up`. | `postgres` service never reports `healthy`; `backend` stays in `created` or `waiting` and does not start (proves `depends_on: condition: service_healthy` is wired). Fix: restore `.env`. |
| 4 | Frontend build context does not include source | Temporarily rename `frontend/src/` and run `make build`. | Frontend image build fails with a clear error (missing entry module). No stale image is tagged under the expected name. Restore `frontend/src/`. |
| 5 | Host port 8000 already occupied | Before `make up`, run `nc -l 8000` (or any process that binds 8000). `make up`. | Compose fails on the `backend` service with "port is already allocated" or equivalent. Other services either did not start or are torn down. No silent fallback to another port. Stop the blocking process to recover. |
| 6 | `MIGRATE=1` but database unreachable | Combine conditions of cases 2 and (implicitly) 1: break `DATABASE_URL`. `make up`. | Backend container exits with a non-zero status from `alembic upgrade head` before uvicorn starts. Logs show the alembic connection error. Compose does not mark backend healthy. |
| 7 | `make clean` on a stack that is not up | From fully-stopped state: `make clean` | Exit status 0. `docker compose down -v` on a down stack is a no-op on containers and still removes the named volumes if present. |

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | Postgres and Redis ports are internal only | After `make up`: `nc -z localhost 5432` and `nc -z localhost 6379` | Both fail with "connection refused". Neither port is published to the host. |
| 2 | Backend container runs as non-root | `docker compose exec backend id` | `uid` is not 0. User matches the one created in the Dockerfile (e.g. `appuser`, uid 1000). |
| 3 | Frontend dev container runs as non-root | `docker compose exec frontend id` | `uid` is not 0. |
| 4 | Named volumes survive `make down` | After case Happy-10, `docker volume ls` filtered to the project prefix | Lists `pgdata`, `redisdata`, `frontend_node_modules`. |
| 5 | Build cache reuse on unchanged code | `make down && make up` without editing any source file | Image layers are cached; no long `uv sync` or `bun install` step is re-executed. Second `make up` completes substantially faster than the first. |
| 6 | Build cache busts on dependency change | Edit `backend/pyproject.toml` to add a harmless dev dependency (remove afterward). `make build`. | The `uv sync` layer in `backend/Dockerfile` rebuilds; layers above it are reused. |
| 7 | `prod` profile builds and serves | `cd infra && docker compose --profile prod build && docker compose --profile prod up -d` | Prod frontend serves built static assets from `nginx:alpine` on the configured `FRONTEND_PORT`. `curl -fsS http://localhost:${FRONTEND_PORT}/` returns HTTP 200 with `server: nginx/...`. Backend runs without `--reload` (no reloader messages in logs). |
| 8 | `.dockerignore` keeps `.env` out of images | `docker build` the backend image, then `docker run --rm <image> ls -a /app` | No `.env` file present in the image. `.env.example` may be present. |
| 9 | `docs/` and `.git/` not copied into images | Inspect image: `docker run --rm <backend-image> ls /app` and similarly for frontend | No `docs/`, `.git/`, `.claude/` directories inside the image. |
| 10 | Makefile `help` target is the default | From repo root: `make` with no target | Prints a list of targets and one-line descriptions; does not run `up`, `build`, or `clean`. |

## Security Considerations

Manual review points rather than executable cases — Vulcan checks these at implementation time; the reviewer verifies during PR review.

- **No hard-coded production credentials.** `infra/.env.example` uses `postgres`/`postgres` as the Postgres superuser/password. This is acceptable for a template because there is no production here; the commit message and README section state that these defaults are for local development only.
- **`infra/.env` is gitignored.** Verified by `git check-ignore infra/.env` returning a match.
- **`.env` / `.env.*` never shipped in images.** Covered by Boundary case 8.
- **Non-root final image.** Covered by Boundary cases 2 and 3.
- **Internal-only data services.** Covered by Boundary case 1.
- **No unauthenticated ports on the host by default.** Only `backend:8000` and `frontend:5173` (or `frontend:8080` in prod) are published. Neither serves destructive endpoints.
- **Image provenance.** All base images are from official Docker Hub namespaces (`library/postgres`, `library/redis`, `library/python`, `library/nginx`, and the widely-used `oven/bun` if chosen). No private or personal registries.
- **Request ID propagation still works.** Indirect check via the `/readyz` response headers including `X-Request-ID`; this verifies `backend/app/middleware.py` runs inside the container the same way it does on a local uvicorn.
- **`make clean` is destructive and is labeled as such.** README and Makefile `help` output both call this out in plain language.

## Forward reference to `feat_testing_001`

The next bootstrap feature, `feat_testing_001`, delivers:

- A `test.sh` driver at the repo root (per `conventions.md` §8 and §10).
- A minimal cross-cutting functional suite exercising the backend's HTTP surface (probably `/healthz`, `/readyz`, `/api/v1/hello`).
- Convention for how backend and frontend unit tests are invoked from `test.sh`.

That suite will **run against a stack brought up by `make up` from this feature.** This test spec therefore intentionally stops at the "services are up and healthy" boundary — proving correctness of application behavior is out of scope here and belongs in `feat_testing_001`. When that feature lands, the happy-path cases above should still pass unchanged; if they do not, that is a regression in `feat_infra_001`, not in `feat_testing_001`.
