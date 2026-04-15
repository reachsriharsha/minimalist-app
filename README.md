# minimalist-app

A minimalist web application template with a **FastAPI** backend, **React + TypeScript** frontend, **Postgres**, and **Redis**, orchestrated via **docker-compose**. The template ships with documentation conventions and an AutoDev workflow (Atlas + Vulcan agents) so new features can be added predictably from day one.

This repository is intended to be consumed via GitHub's **"Use this template"** button. Click it, give your new repo a name, then customize the parts that are project-specific (name in `README.md`, copyright holder in `LICENSE`, and so on).

## Tech stack

- **Backend:** FastAPI, Python (project managed with `uv`), SQLAlchemy, Alembic, structlog
- **Data:** Postgres, Redis
- **Frontend:** Vite + React + TypeScript, managed with `bun` (package manager + script runner; Vite handles the dev server and bundling on Node)
- **Local orchestration:** `docker-compose`
- **Container runtime:** Docker

Specific versions are pinned by the feature that introduces each tool, not here. See [`conventions.md`](conventions.md) for the current locked stack.

## Directory layout

```
minimalist-app/
  conventions.md       # Naming, branching, PR, and label conventions (read this first)
  LICENSE              # MIT license
  README.md            # This file
  docs/
    specs/             # One subfolder per feature, each with 3 spec files
  backend/             # (added by feat_backend_001)   FastAPI service
  frontend/            # (added by feat_frontend_001)  Vite + React + TS app
  infra/               # (added by feat_infra_001)     Dockerfiles, docker-compose, env templates
  tests/               # (added by feat_testing_001)   test.sh driver and cross-cutting tests
  deployment/          # (added by a later infra feature) production artifacts
```

Folders marked "added by `feat_xxx_NNN`" do not exist yet; they land when their owning feature is merged.

## Using this template

1. On GitHub, click **"Use this template"** and create a new repository.
2. Clone the new repo locally.
3. Update the project name, description, and `LICENSE` copyright holder to match your project.
4. Add features one at a time using the AutoDev workflow (see below).

## Getting started

Setup instructions for running the backend, frontend, and local services will be added when the corresponding features land:

- `backend/` run/test instructions come with `feat_backend_001`.
- `frontend/` run/test instructions come with `feat_frontend_001`.
- `make up` / `docker-compose` orchestration comes with `feat_infra_001`.
- `./test.sh` test driver comes with `feat_testing_001`.

Until then, this template ships documentation and conventions only — there is nothing to run.

## Workflow

This template uses the **AutoDev** workflow, in which two agents collaborate with the human:

- **Atlas** plans features and produces three spec files per feature (feature spec, design spec, test spec) on a `spec/<feat_id>` branch.
- **Vulcan** implements merged specs on a `build/<feat_id>` branch, runs tests, and opens a build PR.

Every Atlas session begins by reading [`conventions.md`](conventions.md); every feature's specs live under [`docs/specs/`](docs/specs/). See [`docs/specs/README.md`](docs/specs/README.md) for a guide to reading a feature end-to-end.

## Running with Docker

The full stack (FastAPI backend, Vite + React frontend, Postgres, Redis) runs under `docker-compose`. The compose file lives at [`infra/docker-compose.yml`](infra/docker-compose.yml); a small root `Makefile` wraps the common commands so you do not need to `cd infra` every time.

### Prerequisites

- Docker Engine 20.10+ or Docker Desktop 4.x+, providing `docker compose` (v2).
- Host ports `8000` (backend) and `5173` (frontend dev) must be free.

### First-run setup

```bash
cp infra/.env.example infra/.env
make up
```

`make up` builds the images and starts all four services in the background. On a clean machine the first run takes a minute or two; subsequent runs use cached image layers and start in seconds.

When the stack is healthy:

- Frontend (Vite dev server with HMR): http://localhost:5173
- Backend (FastAPI): http://localhost:8000 — try `http://localhost:8000/readyz` or `http://localhost:8000/api/v1/hello`.
- Postgres and Redis are reachable only on the compose network by design; they do not publish ports to the host.

By default the backend container runs `alembic upgrade head` on startup (controlled by `MIGRATE=1` in `infra/.env`). Alembic no-ops if the database is already at head.

### Common commands

| Command | What it does |
|---|---|
| `make up` | Build and start the dev stack (detached). |
| `make down` | Stop and remove containers. Named volumes are preserved. |
| `make logs` | Tail logs for all services. |
| `make ps` | Show service status. |
| `make build` | Rebuild images without starting services. |
| `make migrate` | Run `alembic upgrade head` as a one-shot. |
| `make clean` | **Destructive.** Stop the stack and delete named volumes (database contents are lost). |
| `make backend-shell` | Open a shell in the running backend container. |
| `make frontend-shell` | Open a shell in the running frontend container. |
| `make db-shell` | Open `psql` in the postgres container. |

### Production profile (optional)

A minimal `prod` profile builds the frontend into a static bundle and serves it from `nginx:alpine`; the backend runs without `--reload`. It is opt-in:

```bash
cd infra && docker compose --profile prod up -d --build
```

This exists so the Dockerfiles are exercised against a production-shape build. It is **not** a deployment story — real deployments (DigitalOcean, AWS, Azure) are the subject of a later infra feature that will populate `deployment/`.

### Source of truth

- Compose topology: [`infra/docker-compose.yml`](infra/docker-compose.yml)
- Env template: [`infra/.env.example`](infra/.env.example) (copy to `infra/.env`; the real file is gitignored)
- Backend image: [`backend/Dockerfile`](backend/Dockerfile)
- Frontend image: [`frontend/Dockerfile`](frontend/Dockerfile)

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for the full text.
