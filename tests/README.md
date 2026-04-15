# minimalist-app — external REST test suite

A black-box functional test suite that hits the compose stack's public HTTP
API and asserts the documented contract. The suite lives in a **separate**
`uv` project (not a workspace member of `backend/`) because, semantically,
these tests are an external consumer of the backend — the same role a
third-party SDK's tests would play.

For the full rationale see
[`docs/specs/feat_testing_001/`](../docs/specs/feat_testing_001/).

## Prerequisites

- Docker Engine 20.10+ or Docker Desktop 4.x with `docker compose` v2.
- [`uv`](https://docs.astral.sh/uv/) on `PATH`. Install with:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` and `curl` (both ubiquitous).
- A populated `infra/.env` (one-time: `cp infra/.env.example infra/.env`).
- Host port `8000` free for the backend (or point `TEST_BASE_URL` elsewhere).

The compose stack itself is owned by
[`feat_infra_001`](../docs/specs/feat_infra_001/) and brought up with
`make up` from the repo root.

## Running the suite

From the repo root:

```bash
./test.sh                # bring up stack if needed, run tests, leave stack up
./test.sh --no-up        # skip bring-up; fail fast if /readyz isn't reachable
./test.sh --down         # run tests, then `make down` (preserves pytest exit code)
```

Directly, without the driver (stack must already be up):

```bash
cd tests && uv run pytest
cd tests && uv run pytest -v          # verbose
cd tests && uv run pytest tests/test_hello.py::test_hello_count_increments_by_one
```

## Configuration

| Variable            | Default                   | Purpose                                              |
|---------------------|---------------------------|------------------------------------------------------|
| `TEST_BASE_URL`     | `http://localhost:8000`   | Backend base URL the suite points at.                |
| `READINESS_TIMEOUT` | `60`                      | Seconds `test.sh` will wait for `/readyz` to return 200. Bump this on slow cold starts (e.g. `READINESS_TIMEOUT=180`). |

Both are read from the environment. The suite never reads `infra/.env` or any
other secret file — only `TEST_BASE_URL`.

## What the suite covers

- `GET /healthz` returns `200` with `{"status": "ok"}`.
- `GET /readyz` returns `200` with `status=="ready"` and both `checks.db=="ok"`
  and `checks.redis=="ok"` (proves Postgres and Redis are reachable from the
  backend over the compose network).
- `GET /api/v1/hello` returns `200` with the documented JSON shape
  (`message: str`, `item_name: str`, `hello_count: int`); two consecutive calls
  increment `hello_count` by exactly 1 (proves the Redis round-trip is live).
- A request to an unknown path returns `404` with the documented error
  envelope: `{"error": {"code": str, "message": str, "request_id": str}}`.
- `X-Request-ID` propagation: a client-supplied value is echoed back verbatim;
  when the client omits the header, the server generates a non-empty one.

Assertions about `hello_count` are **relative** (`second == first + 1`), so
the suite is idempotent on re-runs against a long-lived stack — no Redis
flush required between invocations.

## What is explicitly *not* covered

- **Frontend.** No Vitest, no Playwright, no visual/snapshot tests. Deferred.
- **Backend unit tests.** Those live in `backend/tests/` and are owned by
  `feat_backend_001`.
- **Load, performance, stress, or soak testing.**
- **CI / GitHub Actions.** `test.sh` is CI-friendly but no workflow file is
  added by this feature.
- **Lint / format configuration.** Deferred per `conventions.md` §11.

## Troubleshooting

- **`readiness timeout after 60s`** — the stack did not become healthy within
  the window. Common causes: `infra/.env` missing (`cp infra/.env.example
  infra/.env`), port `8000` bound by another process, first-run image build
  still in progress (bump `READINESS_TIMEOUT`), or Postgres/Redis failing to
  start (check `make logs`).
- **`uv: command not found`** — install `uv` (see Prerequisites).
- **Tests pass locally but fail after a backend change** — you are likely
  running against a stale container. Rebuild: `./test.sh --down && ./test.sh`.
- **Connection refused on `TEST_BASE_URL=http://localhost:9999`** — readiness
  probe will loop until timeout, then exit non-zero. Use the default URL or
  point at a valid backend.
