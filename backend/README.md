# Backend

FastAPI scaffold for the `minimalist-app` template. Managed with [`uv`](https://github.com/astral-sh/uv).

See the full design in [`docs/specs/feat_backend_001/`](../docs/specs/feat_backend_001/) and the project-wide rules in [`../conventions.md`](../conventions.md).

## Prerequisites

- Python >= 3.11
- `uv` installed and on `$PATH`
- A reachable Postgres 14+ and Redis 5+ (only required for `/readyz` and `/api/v1/hello`; `/healthz` works without them)

## First run

```bash
cd backend/
uv sync                        # install deps into backend/.venv/
cp .env.example .env           # edit values if your Postgres/Redis differ
./start.sh migrate             # applies alembic migrations, seeds items row
./start.sh                     # serves on $HOST:$PORT (defaults 0.0.0.0:8000)
```

Hit it:

```bash
curl -s localhost:8000/healthz
curl -s localhost:8000/readyz
curl -s localhost:8000/api/v1/hello
```

## `start.sh`

All runtime commands go through `start.sh` so local and (eventually) Docker entrypoints stay in sync.

| Command                  | What it does                                        |
|--------------------------|-----------------------------------------------------|
| `./start.sh`             | Start uvicorn on `$HOST:$PORT` (defaults shown above) |
| `./start.sh --reload`    | Dev mode with hot reload                            |
| `MIGRATE=1 ./start.sh`   | Run `alembic upgrade head` first, then serve       |
| `./start.sh migrate`     | Run migrations only, exit                           |
| `./start.sh pytest`      | Run the in-container pytest suite                   |

## Tests

```bash
./start.sh pytest
# or
uv run pytest
```

The suite is intentionally small; it is the **developer-loop** smoke test. Tests that need Postgres or Redis skip themselves when the service is unreachable, so a bare `uv run pytest` succeeds (exit code 0) even with no dependencies running. The template's external functional contract is owned by `feat_testing_001`.

## Layout

```
backend/
  pyproject.toml, uv.lock
  alembic.ini
  .env.example      # committed; real .env is gitignored
  start.sh          # single entrypoint (serve, migrate, shell, pytest)
  app/
    main.py         # create_app() factory + module-level ASGI app
    settings.py     # pydantic-settings, .env loader
    logging.py      # JSON logs via structlog
    middleware.py   # RequestIDMiddleware
    errors.py       # global exception handlers + error envelope
    db.py           # async engine, sessionmaker, get_session dependency
    redis_client.py # async redis client + get_redis dependency
    models.py       # Base + Item ORM model
    schemas.py      # response pydantic models
    api/
      health.py     # /healthz, /readyz
      v1/
        hello.py    # /api/v1/hello
  alembic/
    env.py, script.py.mako
    versions/0001_create_items.py
  tests/
    conftest.py
    test_health.py, test_hello.py, ...
```

## Conventions

- One package, `app`. Imports are absolute (`from app.settings import ...`) — no relative imports.
- Every new setting goes in both `app/settings.py` and `.env.example` in the same commit.
- Every non-2xx response body conforms to the error envelope `{"error": {"code", "message", "request_id"}}`.
- Every response carries `X-Request-ID`; every log line produced during a request carries the same `request_id`.

## Out of scope here

Docker, CI, ruff/mypy, auth, frontend, and the external functional test harness are deliberately not configured in this feature. They land in `feat_infra_001`, `feat_testing_001`, `feat_frontend_001`, and deferred conventions PRs respectively.
