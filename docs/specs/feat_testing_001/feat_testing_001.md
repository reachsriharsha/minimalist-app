# Feature: External REST functional test suite

## Problem Statement

The five-feature bootstrap of this template now has a full local stack: `feat_backend_001` (FastAPI service), `feat_frontend_001` (Vite app), and `feat_infra_001` (docker-compose + `make up`) land a running system. What is still missing is a **third-party view** of that system — an external caller that, without importing backend internals or mounting in-process test clients, exercises the public HTTP surface and asserts it behaves as documented.

Concretely, after `make up` a user (human or agent) has no one-command answer to the question "is this stack actually working end-to-end over the network?" The backend's own `backend/tests/` suite runs the app in-process against mocks/fixtures; it does not prove the compose-networked build is healthy, that Redis is reachable from inside the backend container, that the error envelope is what an external client sees, or that the request-ID header survives the real middleware stack at runtime. Those guarantees need an out-of-process black-box check.

This feature delivers that check, plus the `test.sh` driver called out in `conventions.md` §8 as this feature's responsibility, and the `tests/` directory at the repo root.

## Requirements

- Ship a top-level `tests/` directory (per `conventions.md` §8) containing a Python test suite that is a **separate, standalone uv project** — not a workspace member of `backend/`. Rationale: tests are an external consumer of the backend's public HTTP API, not an internal module of it.
- Ship a top-level `test.sh` driver that a user or CI-like runner can invoke from a fresh clone: `./test.sh`. Exit code 0 on pass, non-zero on fail. No silent passes on skipped tests.
- The harness is Python + [pytest](https://docs.pytest.org/) + [httpx](https://www.python-httpx.org/) pinned via `uv`, mirroring the backend's approach (`tests/pyproject.toml` + `tests/uv.lock`). Python requirement `>=3.11` (matches backend).
- The base URL is configurable via the environment variable `TEST_BASE_URL`, defaulting to `http://localhost:8000`. No hard-coded hosts/ports in test bodies.
- `test.sh` is responsible for stack lifecycle. Default behaviour: if `/readyz` is not reachable or not returning 200, bring the stack up (`make up`), wait up to 60 seconds for readiness, then run tests. Do **not** tear the stack down on exit by default — teardown is opt-in via `--down`. Also support `--no-up` for "skip bring-up, fail fast if the stack isn't already healthy" (useful for iterating locally with the stack already running).
- The suite covers, at minimum:
  - `GET /healthz` returns 200 with `{"status": "ok"}`.
  - `GET /readyz` returns 200 with `status=="ready"` and both `checks.db=="ok"` and `checks.redis=="ok"` (proves the compose stack's Postgres and Redis are live from the backend's perspective).
  - `GET /api/v1/hello` returns 200 and JSON matching the shape `{"message": str, "item_name": str, "hello_count": int}` with non-empty strings.
  - `hello_count` **increments by exactly 1** between two consecutive calls — proves the Redis round-trip is live end-to-end without depending on an absolute starting value (see "Test isolation" in the design spec).
  - A request to a deliberately invalid path (e.g. `/__does_not_exist__`) returns HTTP 404 with body shaped exactly as `{"error": {"code": str, "message": str, "request_id": str}}` (the error envelope from `backend/app/errors.py` / `backend/app/middleware.py`).
  - Request-ID propagation: a request with an explicit `X-Request-ID: <uuid>` header receives the same value back in the response's `X-Request-ID` header; a request without the header receives a non-empty `X-Request-ID` in the response (server-generated).
- `tests/README.md` documents: how to run (`./test.sh` from repo root, or `cd tests && uv run pytest`), prerequisites (Docker + the stack from `feat_infra_001`), and the `TEST_BASE_URL` / CLI-flag knobs.

## User Stories

- As a **human developer** cloning this template, I want to run one command (`./test.sh`) and learn within a minute whether the backend is behaving correctly over the wire, so that I can trust the scaffold before building on top of it.
- As an **AI agent** (Vulcan or a downstream builder) working on the backend or infra, I want a single entry point that proves — from outside the process — that a change did not break the public HTTP contract, so that I can gate merges on a real integration signal rather than only on in-process unit tests.
- As a **future feature author** wiring up CI or deployment validation, I want a stable, scriptable pass/fail command over the compose stack, so that I can reuse it without re-writing its lifecycle logic.

## Scope

### In Scope

- `tests/` directory at the repo root with a standalone uv-managed pytest project.
- `test.sh` driver at the repo root with `--down` and `--no-up` flags.
- Fixtures/config layer for `TEST_BASE_URL` and an `httpx.Client` shared across the session.
- The six test areas above (`/healthz`, `/readyz`, `/api/v1/hello` shape, `hello_count` increment, 404 error envelope, `X-Request-ID` propagation).
- `tests/README.md` with run instructions and prerequisites.
- `tests/.gitignore` covering pytest / uv caches (`.venv/`, `__pycache__/`, `.pytest_cache/`).

### Out of Scope

- **Unit tests of backend Python code.** `backend/tests/` already exists and is owned by `feat_backend_001`; this feature does not touch it.
- **Any frontend testing whatsoever.** No Vitest, no Playwright, no component tests, no visual regression, no snapshot tests. The template intentionally defers frontend testing to a future dedicated feature.
- **Load, performance, stress, or soak testing.** Functional REST only.
- **CI / GitHub Actions wiring.** `test.sh` is designed to be CI-friendly, but this feature does not add `.github/workflows/`. A later feature may.
- **Lint / format configuration** for the tests project (no ruff, black, mypy, etc.). Deferred per `conventions.md` §11.
- **Security scanning, SAST, DAST, fuzzing, contract-testing tools** (Pact, Dredd). Assertions are plain pytest `assert`s against `httpx` responses.
- **Automated database reset between tests.** See "Test isolation" in the design spec for the rationale; tests that depend on state (`hello_count`) are written to tolerate arbitrary starting values.
- **Modification of any existing file outside the new `tests/` tree and the new `test.sh`.** In particular: no edits to `backend/`, `frontend/`, `infra/`, or `docs/specs/` other than this feature's own directory. The root `Makefile` is left as-is.

## Acceptance Criteria

- [ ] `tests/pyproject.toml` and `tests/uv.lock` exist; the project is standalone (not listed as a workspace member of `backend/pyproject.toml`).
- [ ] `tests/tests/` (or equivalent) contains at least one test module per the six coverage areas above.
- [ ] `./test.sh` from a freshly cloned repo with Docker running and a copied `infra/.env` exits 0 after bringing the stack up and running the suite.
- [ ] `./test.sh` with the stack already healthy exits 0 without rebuilding anything (readiness probe short-circuits the `make up` call).
- [ ] `./test.sh --no-up` with the stack **down** exits non-zero within the readiness timeout and prints a clear diagnostic (not a stack trace).
- [ ] `./test.sh --down` runs tests, then runs `make down` regardless of pass/fail; the exit code still reflects the test outcome, not the teardown.
- [ ] Stopping Redis (`docker compose -f infra/docker-compose.yml stop redis`) and re-running `./test.sh --no-up` produces a readiness/hello failure with a human-readable message (not a bare exception) and a non-zero exit.
- [ ] `TEST_BASE_URL=http://127.0.0.1:8000 ./test.sh --no-up` works (proves the override path).
- [ ] `tests/README.md` lists the commands above and links back to `feat_infra_001`'s `make up`.
- [ ] No files under `backend/`, `frontend/`, `infra/`, or `docs/` (outside `docs/specs/feat_testing_001/`) are modified.
- [ ] Spec PR and build PR follow `conventions.md` §§3–5 (`spec/feat_testing_001`, `build/feat_testing_001`, `autodev(feat_testing_001): ...` commits, `spec(feat_testing_001): ...` / `build(feat_testing_001): ...` PR titles, labels `autodev` + `feat_testing_001`).
