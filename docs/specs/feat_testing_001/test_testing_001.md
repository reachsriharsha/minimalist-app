# Test Spec: External REST functional test suite

## Scope of this test spec

This feature **is the testing feature.** The artifact it delivers is, itself, a test suite. There is no higher-level automated "test the tester" layer — that would be turtles. Validation here is a **manual checklist** that the builder (Vulcan) runs after implementation and that the human reviewer runs before merging the build PR.

The internal consistency of each test file (imports resolve, fixtures wire correctly, assertions aren't tautologies) is verified by running `./test.sh` against a known-good stack and a known-broken stack and observing the pass/fail split.

Everything below is a manual validation checklist.

## Preconditions

Before running any case:

- Working tree is clean on `main` with `feat_testing_001` merged (or, for pre-merge validation, on the `build/feat_testing_001` branch).
- Docker Engine 20.10+ / Docker Desktop 4.x with `docker compose` v2 installed.
- `uv` installed and on `PATH`.
- `infra/.env` exists (`cp infra/.env.example infra/.env` once).
- No other process bound to host port 8000.
- Start each "clean" case from a stopped stack (`make down`) unless a case says otherwise.

## Happy Path

| # | Test Case | Input / Action | Expected Output |
|---|---|---|---|
| 1 | Cold start: brings stack up and passes | From a stopped stack, `./test.sh` from repo root. | `test.sh` prints "stack not ready … running 'make up'", runs `make up`, prints per-tick waiting lines until `/readyz` returns 200, runs pytest, all tests pass, exit code 0. Stack is still running afterwards (`make ps` shows 4 services). |
| 2 | Warm re-run is fast and idempotent | With the stack from case 1 still up: `./test.sh` again. | Readiness probe returns 200 on the first try; no `make up` invocation; pytest runs; all tests pass; exit code 0. Wall time noticeably shorter than case 1. |
| 3 | Override base URL | With the stack up: `TEST_BASE_URL=http://127.0.0.1:8000 ./test.sh --no-up`. | All tests pass; exit code 0. Pytest output shows the expected number of tests collected. |
| 4 | `--down` tears down after passing | With a healthy stack: `./test.sh --down`. | Tests pass; exit code 0; `make ps` after the command shows no running services from this project (or empty output). Named volumes (`pgdata`, `redisdata`) remain — `--down` calls `make down`, not `make clean`. |
| 5 | `--no-up` with healthy stack | With the stack up: `./test.sh --no-up`. | Readiness probe returns 200 on first try; no `make up` invocation even as a retry; tests run; exit code 0. |
| 6 | Direct pytest invocation works | With the stack up: `cd tests && uv run pytest -v`. | All tests pass; exit code 0. Pytest lists each test with `PASSED`. The session-scoped `readiness_check` fixture runs once at the top; no per-test bring-up. |
| 7 | `hello_count` assertion proves Redis round-trip | Inspect `test_hello.py` assertions and the pass from case 1. | The "increments by exactly 1" test passes regardless of starting `hello_count`. Re-running the suite (case 2) still passes — i.e. the assertion is not coupled to an absolute value. |
| 8 | Error envelope shape passes against a real 404 | Inspect `test_errors.py` assertions and the pass from case 1. | A request to `/__does_not_exist__` receives HTTP 404 and the response JSON has exactly the keys `error.code`, `error.message`, `error.request_id` — verified inside the test. |
| 9 | `X-Request-ID` round-trip passes | Inspect `test_request_id.py` and case 1 pass. | Test a: client-sent header echoed verbatim. Test b: no client header, server-generated non-empty UUID-shaped value present in response. |

## Error Cases

These cases verify that the harness **fails cleanly and loudly** — no silent passes, no confusing stack traces when the failure cause is environmental.

| # | Test Case | Input / State | Expected Behavior |
|---|---|---|---|
| 1 | Stack is fully down, `--no-up` set | `make down` first, then `./test.sh --no-up`. | Readiness loop runs for up to 60 s (default timeout), emits one waiting line per second, then prints a final "readiness timeout after 60s" line to stderr and exits with a **non-zero** code. No Python stack trace. |
| 2 | Stack is fully down, no flags, readiness still times out | Contrived: break `infra/.env` so `make up` starts services that cannot become healthy (e.g. `POSTGRES_PASSWORD=` empty, as in `feat_infra_001` test spec). `./test.sh`. | `make up` invoked, services started, readiness probe keeps returning non-200, timeout fires at 60 s, non-zero exit. Clear error message. Restore `.env` afterwards. |
| 3 | Redis stopped mid-stack | With a healthy stack up, `docker compose -f infra/docker-compose.yml stop redis`. `./test.sh --no-up`. | Readiness probe returns 503 (`checks.redis` != `"ok"`), loop times out waiting for `ready`, non-zero exit. If the probe *does* succeed before Redis is checked (race), then `test_readyz` in pytest fails with an assertion on `checks.redis == "ok"` — a readable pytest failure, non-zero exit. Either path is acceptable. |
| 4 | Postgres stopped mid-stack | Same as case 3 but `stop postgres`. | Analogous: either readiness times out or `test_readyz` fails on `checks.db == "ok"`. Non-zero exit with readable diagnostic. |
| 5 | Wrong base URL | `TEST_BASE_URL=http://localhost:9999 ./test.sh --no-up`. | Readiness probe immediately fails (connection refused from curl); loop runs to timeout; non-zero exit. No Python stack trace at the shell level. |
| 6 | Unknown CLI flag | `./test.sh --froboz`. | `test.sh` prints `unknown argument: --froboz` to stderr and exits with code 2 (or any well-defined non-zero) *without* attempting `make up` or `pytest`. |
| 7 | `uv` not on PATH | Temporarily `PATH=/usr/bin:/bin ./test.sh --no-up` (stack healthy). | Shell prints `uv: command not found` (or the equivalent), non-zero exit. The failure surfaces at the `uv run` step, not earlier. Restore `PATH` afterward. |
| 8 | Broken backend contract (regression check) | Temporarily edit `backend/app/api/v1/hello.py` to return `hello_count` as a *string* instead of `int`. `make up --build` (or let compose hot-reload). `./test.sh --no-up`. | `test_hello` shape assertion fails with a clear pytest diff. Non-zero exit. Revert the edit; re-run passes. **Do not commit this change.** |
| 9 | Broken error envelope (regression check) | Temporarily edit `backend/app/errors.py` to return a non-enveloped body for 404s. Rebuild. `./test.sh --no-up`. | `test_errors` fails with a clear pytest diff on missing `error.*` keys. Non-zero exit. Revert. |
| 10 | Broken request-ID middleware (regression check) | Temporarily remove `X-Request-ID` from the response in `backend/app/middleware.py`. Rebuild. `./test.sh --no-up`. | `test_request_id` fails on both the echo case and the generation case. Non-zero exit. Revert. |

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | Readiness timeout is configurable | `READINESS_TIMEOUT=5 ./test.sh` against a stopped stack that will take longer than 5 s to come up. | Timeout fires at ~5 s (not 60 s); non-zero exit. Proves the env var is honored. |
| 2 | Suite works from a subdirectory | `cd tests/ && ../test.sh`. | Behaves identically to running from repo root (because `test.sh` resolves its own directory). All tests pass when the stack is healthy. |
| 3 | Concurrent re-invocations | Start `./test.sh` in two terminals back-to-back against a healthy stack. | Both exit 0. No port conflicts (tests are pure HTTP clients; no fixtures bind host ports). The `hello_count` increment-by-1 assertion holds because each test function uses a single client and fetches both values in sequence, inside the same test — there is no cross-test timing dependency. |
| 4 | Empty `X-Request-ID` from client | The test file asserts behavior when the client sends `X-Request-ID: ` (empty). | Per `backend/app/middleware.py:40-41`, an empty header is treated as absent, and the server generates a UUID. Test passes. (Optional boundary test; include if Vulcan sees it as low-cost.) |
| 5 | Suite is hermetic w.r.t. working directory | `uv run pytest` from `tests/` with no env vars set and stack up. | Default `TEST_BASE_URL=http://localhost:8000` applies; tests pass. No tests read or write files on the host. |
| 6 | `./test.sh --down` still exits with test code on failure | Introduce a deliberate test failure (case 8 in Error Cases) then run `./test.sh --down`. | Tests fail → pytest exits non-zero → `make down` still runs → final exit code is pytest's non-zero code, *not* make's. Revert the broken change afterward. |
| 7 | No new dependencies | `grep -c '^\w' tests/pyproject.toml` (or manual inspection). | Only `pytest` and `httpx` in `[project].dependencies` (or the uv equivalent). No transitive pins hand-written into the TOML; uv owns the lock. |
| 8 | Tests do not import from `backend` | `grep -R "from app" tests/ ; grep -R "import app" tests/` | No matches. The suite has **zero** imports from the backend package; it sees only HTTP. |
| 9 | No frontend imports or calls | `grep -R "5173" tests/ ; grep -R "frontend" tests/` | No matches. The suite does not touch the frontend in any way. |

## Security Considerations

Manual review points. Because this is a test-harness feature, the security surface is small, but a few things are worth verifying during PR review:

- **No secrets in the test suite.** `tests/` does not read or assert against `infra/.env` values. The suite connects to `TEST_BASE_URL` and nothing else. Verified by inspection.
- **No credentials in logs.** `test.sh` does not echo `DATABASE_URL`, `REDIS_URL`, or any env-var value. Readiness probe output shows only the URL (`http://localhost:8000/readyz`) and a generic wait message.
- **No arbitrary command execution via flags.** `test.sh` only accepts `--down`, `--no-up`, `-h`/`--help`. Anything else exits non-zero (Error case 6). No `eval`, no `$1` unquoted, no passing of argv into `make` or `pytest` (yet — if flag pass-through is ever added, it must be explicit and validated).
- **`curl` against localhost only by default.** `TEST_BASE_URL` defaults to `http://localhost:8000`; a malicious clone cannot redirect the probe to a remote host without the user explicitly setting the env var. Documented in `tests/README.md`.
- **No privileged operations.** `test.sh` does not invoke `docker` directly — only via `make up` / `make down`, which are already owned by `feat_infra_001`. Adding raw `docker` calls later is deliberately out of scope.
- **`uv run` uses the committed `tests/uv.lock`.** Reproducible dependency resolution; no live network fetch of an unpinned version. Verified by running on an air-gapped host with a pre-warmed uv cache (nice-to-verify, not required for merge).
- **Tests never write to Postgres or Redis directly.** All state changes happen through the backend's public API, which enforces its own authorization rules (none, in this scaffold — but the pattern is correct for when auth is added later).

## Forward-looking notes (not blocking this feature)

- A future feature may wrap `./test.sh` in a GitHub Actions workflow. The contract this feature establishes — "exit 0 on pass, non-zero on fail, `--down` for one-shot CI, readiness built-in" — is intentionally CI-friendly without hard-coding any CI provider here.
- A future feature may add frontend tests under a new top-level `frontend/tests/` or similar. `test.sh` can be extended to fan out into multiple suites; that extension is deferred and is not assumed here.
- A future feature may add per-test state isolation (Redis `FLUSHDB`, DB transaction rollback). That is a contract change (tests would become order-independent and mutation-safe); it is deferred until an actual need surfaces.
