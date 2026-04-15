# Test Spec: FastAPI backend scaffold

## Scope and audience

This feature ships two *kinds* of test expectations, and they must not be confused:

1. **In-container `pytest` suite** under `backend/tests/`. This is a **developer-loop** suite that Vulcan writes as part of this feature. It runs with `uv run pytest` from `backend/`. It is intentionally minimal. It is **not** the template's acceptance contract.
2. **External functional expectations** that a later feature (`feat_testing_001`) will codify as the template's contract. We list them here so `feat_testing_001` has a concrete starting point and so reviewers can verify the scaffold is testable from the outside.

Both sections below are written as concrete, checkable cases, not prose.

---

## Section A — In-container pytest suite (Vulcan implements these)

Located at `backend/tests/`. All cases run via `uv run pytest` from `backend/`.

### A.1 Happy Path

| # | Test case | Input / preconditions | Expected output |
|---|---|---|---|
| A1.1 | `test_healthz_returns_ok` | `httpx.AsyncClient` against the ASGI app; no DB or Redis required. | HTTP 200; body `{"status": "ok"}`; response includes `X-Request-ID` header (non-empty). |
| A1.2 | `test_readyz_when_both_deps_up` | Live Postgres and Redis reachable at configured URLs (skip otherwise). | HTTP 200; body matches `{"status": "ready", "checks": {"db": "ok", "redis": "ok"}}`. |
| A1.3 | `test_hello_round_trips_db_and_redis` | Live Postgres with `items` seeded via `alembic upgrade head`; live Redis (skip otherwise). Call `/api/v1/hello` twice. | Both calls return 200; `item_name == "hello"`; `hello_count` strictly increases between the two calls (proves Redis write happened). |
| A1.4 | `test_request_id_echoed_when_supplied` | Send `X-Request-ID: test-abc-123` to `/healthz`. | Response `X-Request-ID` header equals `test-abc-123`. |
| A1.5 | `test_request_id_generated_when_absent` | Send request to `/healthz` without `X-Request-ID`. | Response `X-Request-ID` header is present, non-empty, and is a valid UUID (or at least a non-trivial string of length >= 8). |

### A.2 Error Cases

| # | Test case | Input | Expected behavior |
|---|---|---|---|
| A2.1 | `test_unknown_route_returns_404_in_envelope` | `GET /does-not-exist`. | HTTP 404; body matches error envelope with `error.code == "http_error"` and a non-empty `error.request_id`. |
| A2.2 | `test_readyz_when_db_down` | Override `database_url` to an unreachable URL for this test's app instance; Redis still up. | HTTP 503; body's `checks.db` is a non-empty string **not** equal to `"ok"`; `checks.redis == "ok"`; `status == "not_ready"`. |
| A2.3 | `test_readyz_when_redis_down` | Override `redis_url` to an unreachable URL; Postgres still up. | HTTP 503; `checks.redis != "ok"`; `checks.db == "ok"`; `status == "not_ready"`. |
| A2.4 | `test_unhandled_exception_returns_envelope` | Register a temporary route that raises `RuntimeError("boom")` on a test-only app instance, then call it. | HTTP 500; body matches error envelope with `error.code == "internal_error"`, `error.message == "Internal Server Error"` (no traceback in body), and `error.request_id` matches the response header. |

### A.3 Boundary Conditions

| # | Test case | Condition | Expected behavior |
|---|---|---|---|
| A3.1 | `test_healthz_works_without_any_dependencies` | Set `DATABASE_URL` and `REDIS_URL` to obviously invalid values; import `app.main` and call `/healthz`. | App imports without error; `/healthz` returns 200. Proves the scaffold does not connect at import. |
| A3.2 | `test_app_factory_isolates_state` | Call `create_app()` twice, send a request to each. | Both apps answer; neither throws; the two instances do not share `app.state.redis` identity. (Light sanity check; prevents global-state regressions.) |

### A.4 Skip behavior

| # | Rule | Expected behavior |
|---|---|---|
| A4.1 | `require_db` fixture | On Postgres connection failure, `pytest.skip("postgres not reachable at <url>")`. Does not fail. |
| A4.2 | `require_redis` fixture | On Redis connection failure, `pytest.skip("redis not reachable at <url>")`. Does not fail. |
| A4.3 | Running `uv run pytest` with no DB/Redis available | A1.1, A1.4, A1.5, A2.1, A2.4, A3.1, A3.2 must still pass. Everything else skips. Exit code 0. |

### A.5 Security considerations (in-container scope)

| # | Concern | Check |
|---|---|---|
| A5.1 | Error responses must not leak tracebacks. | A2.4 asserts `error.message == "Internal Server Error"` and no `"Traceback"` substring in the body. |
| A5.2 | Secrets do not appear in logs by default. | `conftest.py` captures logs during A2.4 and asserts the log record contains `request_id` but does not contain the substring `"password"` (sanity guard — there is no password in this scaffold, but this encodes the intent). |
| A5.3 | `.env` is not tracked. | A shell assertion in `conftest.py` (or a dedicated `test_repo_hygiene.py`) runs `git ls-files backend/.env` and asserts empty output. Skips if not in a git checkout. |

---

## Section B — External functional expectations (for `feat_testing_001` to codify)

These are the assertions the eventual external test suite (`tests/` at repo root, driven by `test.sh`) must make about a running backend container. They are listed here so the scaffold is built to satisfy them from day one.

### B.1 Endpoint contract

| # | Assertion | How it will be checked externally |
|---|---|---|
| B1.1 | `GET /healthz` returns `200` with JSON body `{"status": "ok"}`. | `curl -fsS http://backend:8000/healthz | jq -e '.status == "ok"'`. |
| B1.2 | `GET /readyz` returns `200` with `status="ready"` and both `checks.db` and `checks.redis` equal to `"ok"` when the compose stack is healthy. | `curl` + `jq -e '.status == "ready" and .checks.db == "ok" and .checks.redis == "ok"'`. |
| B1.3 | `GET /readyz` returns `503` when Postgres is stopped. | Stop the `db` service in compose, poll `/readyz`, assert `503` and `checks.db != "ok"` within a timeout. |
| B1.4 | `GET /readyz` returns `503` when Redis is stopped. | Same as B1.3 but for the `redis` service. |
| B1.5 | `GET /api/v1/hello` returns `200` with fields `message` (string), `item_name == "hello"`, and `hello_count` (integer, strictly positive). Two sequential calls see a monotonically increasing `hello_count`. | Two `curl`s with `jq` assertions. |
| B1.6 | Every response carries a non-empty `X-Request-ID` header. If the request supplied one, it is echoed verbatim. | `curl -i` + header parsing. |
| B1.7 | `GET /nonexistent` returns `404` with the documented error envelope (`error.code`, `error.message`, `error.request_id`). | `jq -e '.error.code == "http_error" and (.error.request_id | length) > 0'`. |

### B.2 Response shape invariants

| # | Assertion |
|---|---|
| B2.1 | Every non-2xx response body conforms to `{"error": {"code": str, "message": str, "request_id": str}}`. Extra keys allowed; missing keys fail the contract. |
| B2.2 | Successful responses are valid JSON (not newline-delimited, not empty). |
| B2.3 | Logs emitted to stdout (captured via `docker logs backend`) are valid JSON, one object per line, and contain `request_id` for any log line produced during a request. |

### B.3 Lifecycle

| # | Assertion |
|---|---|
| B3.1 | Fresh stack: after `docker compose up -d`, polling `/readyz` reaches `200` within a reasonable budget (to be pinned by `feat_testing_001` / `feat_infra_001`; suggested 60s). |
| B3.2 | After `docker compose down -v` and a fresh `up`, the database is re-migrated automatically or via a documented entrypoint, and B1.5 passes again (`item_name == "hello"`). `feat_infra_001` decides who runs `alembic upgrade head`; the scaffold simply must not require magic. |

### B.4 Security / hygiene invariants

| # | Assertion |
|---|---|
| B4.1 | No file under `backend/` contains a real secret. Specifically: `backend/.env` is **not** in `git ls-files`; `backend/.env.example` is; `backend/.env.example` contains only dev-safe placeholder values. |
| B4.2 | A 500 response from any endpoint (triggered, e.g., by a deliberate fault-injection endpoint behind an env flag if `feat_testing_001` adds one — **not part of this feature**) must not include the strings `"Traceback"`, `"File \""`, or stack frame paths in the body. |
| B4.3 | CORS, auth, and cookies are not configured by this feature. Any future feature that needs them adds them under its own spec. The external suite must not assume their presence.

---

## Out of scope for this test spec

- Load/performance testing.
- Migration rollback correctness beyond "downgrade drops the table" (future migrations will add their own cases).
- Multi-instance coordination (no clustering in this scaffold).
- Anything requiring the frontend, Docker, or `test.sh` — those are tested under `feat_frontend_001`, `feat_infra_001`, and `feat_testing_001` respectively.
