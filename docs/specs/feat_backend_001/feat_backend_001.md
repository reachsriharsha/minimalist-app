# Feature: FastAPI backend scaffold

## Problem Statement

The repository currently has only conventions, licensing, and a spec directory. It contains no runnable code. To become a useful template, it needs a minimal, opinionated Python service that demonstrates the locked backend stack (FastAPI + Postgres + Redis, managed with `uv`) wired end-to-end. This feature establishes that service as the second of five bootstrap features.

The scaffold must be complete enough that a future implementer can:

- Run the app locally (via `uv run` — Docker orchestration arrives in `feat_infra_001`).
- See a live endpoint that round-trips through both Postgres and Redis, proving both are wired.
- Hit `/healthz` for a liveness probe and `/readyz` for a readiness probe that reflects real dependency health.
- Add a new endpoint, model, or migration without inventing a layout — the conventions are fixed here.

It must be **narrow enough** to leave room for later features: no Docker, no linting, no external functional tests, no auth, no frontend.

## Requirements

### Functional

1. A FastAPI application exposing:
   - `GET /healthz` — always returns `200 {"status": "ok"}` if the process is alive.
   - `GET /readyz` — returns `200 {"status": "ready", "checks": {...}}` when both Postgres and Redis respond to a trivial probe; returns `503 {"status": "not_ready", "checks": {...}}` otherwise, with each dependency reported as `"ok"` or an error string.
   - `GET /api/v1/hello` — returns a JSON payload proving both Postgres and Redis are reachable in a single request (e.g., reads a seeded row from Postgres and reads/writes a counter in Redis).
2. A versioned API router mounted at `/api/v1/`. New endpoints go through this router.
3. A global exception handler that converts unhandled exceptions into a consistent JSON error envelope (shape defined in the design spec).
4. Structured JSON logging via `structlog`, with a per-request correlation ID (request ID) attached to every log line and to the response headers.
5. Settings loaded via `pydantic-settings` from environment variables and a `.env` file in `backend/`. A `backend/.env.example` documents every setting.
6. SQLAlchemy 2.x async ORM with `asyncpg` as the Postgres driver; sessions provided via a FastAPI dependency.
7. Alembic configured for async migrations, with at least one migration that creates a trivial `items` table used by the hello-world endpoint. Seeding the single demo row may happen in the migration or at app startup — the design spec picks one.
8. `redis.asyncio` client provided via a FastAPI dependency, initialized at startup and closed at shutdown.
9. An in-container `pytest` skeleton under `backend/tests/` with at least two smoke tests. This is a **developer-loop** suite, explicitly not the template's contract — the external functional suite is owned by `feat_testing_001`.

### Non-functional

10. Python dependency management is `uv` (per conventions): `backend/pyproject.toml` declares dependencies; `backend/uv.lock` is committed.
11. A single Python package `app` lives under `backend/app/`. Imports use `app.*`, not relative.
12. Code is readable without linting tools (those arrive later); no emoji in source; type hints on public functions.
13. No secrets in the repo. `.env` is gitignored inside `backend/`; `.env.example` is committed.
14. The scaffold must start up cleanly without a database or Redis present for `/healthz` alone — dependency failures must not crash app import or the liveness endpoint. They are only reflected in `/readyz` and at the moment dependent endpoints are called.

## User Stories

- As a **template consumer**, I want a working FastAPI app with Postgres + Redis already wired, so I can start adding endpoints without re-deciding the stack.
- As **Vulcan** (builder), I want unambiguous file paths, module boundaries, and the error/log shape pinned down, so my implementation PR is a straight-line translation of the design spec.
- As **an operator**, I want separate liveness and readiness endpoints so an orchestrator can distinguish a crashed process from one whose dependencies are temporarily unavailable.
- As **a future feature author** (`feat_frontend_001`, `feat_testing_001`), I want `/api/v1/hello` to return a stable JSON shape I can call from the browser or a test runner.

## Scope

### In Scope

- Everything under `backend/`:
  - `backend/pyproject.toml`, `backend/uv.lock`
  - `backend/app/` package: entrypoint, settings, logging, middleware, routers, DB session, Redis client, models, schemas, exception handlers.
  - `backend/alembic/` directory with `env.py`, `script.py.mako`, and a `versions/` folder containing the initial migration.
  - `backend/alembic.ini`
  - `backend/.env.example`
  - `backend/.gitignore` covering `.env`, `__pycache__/`, `.pytest_cache/`, `.venv/`, etc.
  - `backend/tests/` with `conftest.py` and a small number of smoke tests.
  - `backend/README.md` with a short "how to run locally" note (does not overlap with the top-level README).

### Out of Scope

- Docker image, Dockerfile, and `docker-compose.yml` (→ `feat_infra_001`).
- `test.sh` and the external functional test suite (→ `feat_testing_001`).
- Frontend code (→ `feat_frontend_001`).
- Linting/formatting tools (`ruff`, `mypy`, `black`) — explicitly deferred per `conventions.md` §11.
- Authentication, authorization, sessions, CSRF, rate limiting.
- Celery, background workers, task queues.
- User accounts, any domain models beyond the trivial `items` demo.
- Production deployment concerns (Gunicorn tuning, observability backends, tracing).
- OpenAPI customization beyond FastAPI defaults.

## Acceptance Criteria

- [ ] `backend/pyproject.toml` exists, uses `uv` project layout, and declares at minimum: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `asyncpg`, `alembic`, `redis>=5`, `pydantic-settings`, `structlog`, `pytest`, `pytest-asyncio`, `httpx`. `backend/uv.lock` is committed.
- [ ] `backend/.env.example` lists every setting the app reads, with safe dev defaults and comments.
- [ ] `backend/.env` is gitignored; no real secrets appear in any committed file.
- [ ] `uv run uvicorn app.main:app` (run from `backend/`) starts the server on a configurable port.
- [ ] `GET /healthz` returns `200 {"status": "ok"}` without touching Postgres or Redis.
- [ ] `GET /readyz` returns `200` with `checks.db == "ok"` and `checks.redis == "ok"` when both are reachable; returns `503` with the failing dependency's error string when either is down.
- [ ] `GET /api/v1/hello` returns a `200` JSON payload that contains at least: a greeting string, the value read from Postgres, and the Redis counter value after increment.
- [ ] Every response carries an `X-Request-ID` header; if the request supplied one, it is echoed, otherwise one is generated. Every log line for that request includes the same request ID.
- [ ] Logs emit as single-line JSON on stdout.
- [ ] An unhandled exception from any endpoint produces a `500` response whose body matches the documented error envelope, and a log line at error level with the traceback.
- [ ] `alembic upgrade head` applies cleanly from an empty database and creates the `items` table.
- [ ] `uv run pytest` from `backend/` runs the smoke tests to green (using a test DB URL / test Redis URL supplied via env). If Postgres/Redis are unavailable, tests that need them skip with a clear reason rather than failing.
- [ ] All files that Vulcan creates live under `backend/` — no top-level or cross-domain files are modified by this feature.
- [ ] `docs/specs/README.md` feature roster row for `feat_backend_001` is updated to reflect `In Build` / `Merged` as the lifecycle advances (Atlas does not do this in the spec PR; Vulcan updates it in the build PR per status vocabulary).
