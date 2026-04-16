# Test: Auth foundation — users, roles, identities, sessions

## Scope

This feature lands schema, session plumbing, and authorization primitives. It introduces **no real login path** — the only way to mint a session in this feature is `POST /api/v1/_test/session`, which is gated to `env == "test"`. Tests therefore:

1. Unit-test every helper in isolation (sessions, dependencies, bootstrap).
2. Integration-test the middleware + `/auth/me` + `/auth/logout` pair end-to-end using the test-only mint.
3. Verify the test-only mint is absent when `env != "test"`.
4. Verify the Alembic migration stands up a clean schema and tears it down cleanly.

Coverage of the OTP flow (§9.1/§9.2 of the design doc, OTP rows) and the Google OAuth flow (Google rows of §9.2) is **out of scope** — those land with `feat_auth_002` and `feat_auth_003`. Only tests that exercise this feature's actual endpoints and dependencies are listed here.

## New test files

### `backend/tests/test_auth_sessions.py`

Unit-tests `backend/app/auth/sessions.py` against a real Redis (existing test fixture provides one; tests skip with a clear reason when Redis is unreachable).

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 1 | `create` round-trip | Mint a session for `user(id=42, email=a@x.com, roles=[user])`. | Returned `session_id` is 64 hex chars. `GET session:<id>` exists in Redis with the same payload. `user_sessions:42` contains `session_id`. Both keys TTL > 86300 and ≤ 86400. |
| 2 | `get` returns `AuthContext` | Given a session minted by case 1. | `sessions.get(session_id, redis=...)` returns an `AuthContext(user_id=42, email='a@x.com', roles=('user',), session_id=session_id)`. |
| 3 | `get` missing key | No mint; random session_id. | Returns `None`. |
| 4 | `get` malformed payload | Manually write a non-JSON string to `session:<id>`. | Returns `None`. No exception propagates. |
| 5 | `delete` wipes both keys | Mint, then `delete`. | `GET session:<id>` returns `None`. Session id is no longer in `user_sessions:42`. |
| 6 | `revoke_all_for_user` | Mint two sessions for the same user_id. | After call, both `session:*` keys are gone. `user_sessions:42` is gone. |
| 7 | `revoke_all_for_user` when reverse-index is empty | Never-logged-in user id. | Call completes without error; no keys touched. |
| 8 | TTL is exactly `SESSION_TTL_SECONDS` | Mint with settings.session_ttl_seconds=10. | `TTL session:<id>` ∈ [9, 10]. `TTL user_sessions:<uid>` ∈ [9, 10]. |

### `backend/tests/test_auth_middleware.py`

Integration tests against `create_app(Settings(env="test"))` with `SessionMiddleware` installed. Uses `httpx.AsyncClient`.

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 1 | No cookie, public endpoint | `GET /healthz` with no cookie. | HTTP 200. No `Set-Cookie` emitted by the middleware. `request.state.auth` is `None` (inspected via a test-only introspection route that returns the string `None` or the type name — see "Introspection helper" below). |
| 2 | Valid cookie populates context | Mint a session via `/api/v1/_test/session` then `GET` a route that echoes `request.state.auth.roles`. | HTTP 200. Body contains the minted user's `user_id`, `email`, and `roles`. No DB queries recorded during the `/auth/me`-equivalent call (see "Zero-DB-hit assertion" below). |
| 3 | Expired session clears cookie | Mint; then manually `DEL session:<id>` in Redis. Call `GET /api/v1/auth/me`. | HTTP 401. Response `Set-Cookie` header has `Max-Age=0` for `SESSION_COOKIE_NAME`. Log event `auth.session.expired_cookie_cleared reason=missing_key` emitted. |
| 4 | Malformed payload clears cookie | Mint; manually overwrite `session:<id>` with the bytes `not json`. Call `GET /api/v1/auth/me`. | HTTP 401. `Set-Cookie` clears the cookie. Log event `auth.session.expired_cookie_cleared reason=malformed_payload` emitted. |
| 5 | Cookie with impossible characters | Send `Cookie: session=<60 hex>` (wrong length). | HTTP 401. Cookie cleared. Log event `auth.session.expired_cookie_cleared reason=malformed_cookie` emitted. |
| 6 | Middleware runs after RequestID | Inspect log line from case 3; confirm it carries `request_id`. | `request_id` present in the JSON — proves `RequestIDMiddleware` is still outermost. |

**Introspection helper:** tests that need to verify `request.state.auth` contents without shipping a production "inspect my session" route use `GET /api/v1/auth/me` (which exists in this feature). The middleware behavior is fully observable through the public endpoint; no debug route is added.

**Zero-DB-hit assertion:** wrap the test's `AsyncClient` call in a context manager that records SQLAlchemy query events on the test engine. `events.listen(engine.sync_engine, "before_cursor_execute", ...)` collects fired statements. `/auth/me` must show zero. `POST /auth/logout` is also zero.

### `backend/tests/test_auth_dependencies.py`

Unit tests for `current_user`, `require_authenticated`, `require_roles`. Uses FastAPI's `dependency_overrides` to inject a fabricated `request.state.auth` via a stub middleware-equivalent.

| # | Case | `request.state.auth` | Dependency | Expected |
|---|---|---|---|---|
| 1 | Authenticated | `AuthContext(user_id=1, email='a@x', roles=('user',), session_id='...')` | `current_user` | returns the context |
| 2 | Unauthenticated | `None` | `current_user` | HTTPException(401, `not_authenticated`) |
| 3 | `require_authenticated` is an alias | `None` | `require_authenticated` | HTTPException(401, `not_authenticated`) |
| 4 | Single required role — match | roles=`('user',)` | `require_roles("user")` | returns the context |
| 5 | Single required role — miss | roles=`('user',)` | `require_roles("admin")` | HTTPException(403, `forbidden`) |
| 6 | Multiple roles — OR semantics, first matches | roles=`('admin',)` | `require_roles("admin", "user")` | returns |
| 7 | Multiple roles — OR semantics, second matches | roles=`('user',)` | `require_roles("admin", "user")` | returns |
| 8 | Multiple roles — neither | roles=`('guest',)` | `require_roles("admin", "user")` | 403 `forbidden` |
| 9 | `require_roles` with no cookie | `request.state.auth = None` | `require_roles("admin")` | 401 `not_authenticated` (not 403 — unauth precedes auth-z) |

### `backend/tests/test_auth_bootstrap.py`

Unit tests for `backend/app/auth/bootstrap.py`.

| # | Case | `ADMIN_EMAILS` | User email | Expected |
|---|---|---|---|---|
| 1 | Empty list never grants | `""` | `alice@x.com` | `grant_admin_if_listed` returns `False`; user's role collection unchanged. |
| 2 | Exact match grants | `"alice@x.com"` | `alice@x.com` | Returns `True`; user gains an `admin` role row. |
| 3 | Case-insensitive match | `"ALICE@x.com"` | `alice@x.com` | Returns `True`; user gains `admin`. |
| 4 | Whitespace-tolerant | `" alice@x.com , bob@x.com "` | `bob@x.com` | Returns `True`. |
| 5 | Non-member | `"alice@x.com,bob@x.com"` | `carol@x.com` | Returns `False`. |
| 6 | Settings cache reflects env | Set env var via monkeypatch, call `reset_settings_cache()`, re-read. | lookup reflects new value | Confirms no stale cache. |
| 7 | Idempotent | Apply twice in sequence for a match. | `user.roles` contains exactly one `admin`, not two. |

### `backend/tests/test_auth_me_logout.py`

End-to-end tests against `create_app(Settings(env="test"))`. Exercises the full mint → `/me` → `/logout` → `/me` lifecycle via the test-only endpoint.

| # | Flow | Steps | Assertion |
|---|---|---|---|
| 1 | Happy path | POST `/_test/session` `{email: a@x.com, display_name: Alice}` → carry cookie → GET `/auth/me` → POST `/auth/logout` → GET `/auth/me` | Mint: 200 + `Set-Cookie`. `/auth/me` (1): 200 with payload `{user_id, email: 'a@x.com', display_name: 'Alice', roles: ['user']}`. `/auth/logout`: 204 + cookie cleared. `/auth/me` (2): 401. |
| 2 | ADMIN_EMAILS bootstrap | Settings with `ADMIN_EMAILS="alice@x.com"`. POST `/_test/session` `{email: alice@x.com}`. GET `/auth/me`. | Response `roles` contains both `user` and `admin`. |
| 3 | Non-bootstrap user | Same settings, mint `bob@x.com`. | Roles is exactly `["user"]`. |
| 4 | Extra roles parameter | POST `/_test/session` `{email: a@x.com, roles: ["admin"]}`. GET `/auth/me`. | Roles contains `admin` **and** `user` (user always granted as the default). |
| 5 | Existing user — idempotent mint | Mint twice with the same email and no extra roles. | Both calls succeed. DB `users` has exactly one row for that email. `auth_identities` has zero rows (the test-mint skips identity creation — documented behavior, since identities are created only by real login paths in 002/003). |
| 6 | `revoke_sessions_for_user` end-to-end | Mint session A for user. Mint session B for the same user. Call `service.revoke_sessions_for_user(user.id, redis=...)`. GET `/auth/me` with cookie A → 401. GET `/auth/me` with cookie B → 401. | Both sessions dead. `user_sessions:<uid>` is gone. |
| 7 | No cookie → `/auth/me` | GET `/auth/me` with no cookie. | 401 `not_authenticated`. |
| 8 | Logout without session | GET `/auth/me` with no cookie → 401. Then POST `/auth/logout` with no cookie. | 401 `not_authenticated`. No Redis delete was attempted (verified by a Redis-command recorder). |
| 9 | Cookie attributes | Mint; inspect the `Set-Cookie` header. | Contains `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=86400`. Does **not** contain `Secure` when `SESSION_COOKIE_SECURE=false`. Does contain `Secure` when `SESSION_COOKIE_SECURE=true`. |

### `backend/tests/test_auth_test_mint_gating.py`

Verifies the test-only mint endpoint is present only under `env == "test"`.

| # | Case | Build with | Expected |
|---|---|---|---|
| 1 | Not mounted in dev | `create_app(Settings(env="dev"))` | POST `/api/v1/_test/session` returns 404. |
| 2 | Not mounted in prod | `create_app(Settings(env="prod"))` | POST `/api/v1/_test/session` returns 404. |
| 3 | Mounted in test | `create_app(Settings(env="test"))` | POST `/api/v1/_test/session` with a valid body returns 200. |
| 4 | Real `/auth/me` always mounted | Build under each of dev/test/prod. | `GET /api/v1/auth/me` with no cookie returns 401 in all three — endpoint is registered regardless of env. |

### Alembic migration test — `backend/tests/test_migration_0002_auth.py`

Verifies the new migration stands up and tears down cleanly against a real Postgres. Existing tests already depend on Alembic at session scope; this adds one focused test.

| # | Case | Steps | Assertion |
|---|---|---|---|
| 1 | Clean upgrade | `alembic downgrade base`; `alembic upgrade head`. | `users`, `roles`, `user_roles`, `auth_identities` all exist. `roles` contains exactly two rows, `admin` and `user`. `citext` extension is present. |
| 2 | Clean downgrade | After case 1, `alembic downgrade -1`. | All four tables absent. `citext` extension absent (or still present if another migration needed it — 001 is the first, so absent). |
| 3 | Email case-insensitivity | After upgrade, `INSERT users(email='Alice@X.com'); INSERT users(email='alice@x.com')`. | Second insert fails with a `citext` uniqueness violation. |
| 4 | `ON DELETE CASCADE` on user deletion | Insert user, `user_roles` row, `auth_identities` row. DELETE user. | `user_roles` row and `auth_identities` row are both gone. |
| 5 | `ON DELETE RESTRICT` on role deletion | Attempt to DELETE the `admin` role while it is referenced. | Fails with an FK violation. |
| 6 | Auto-generated names use convention | Inspect pg_catalog for constraint names. | `pk_users`, `uq_users_email`, `pk_roles`, `uq_roles_name`, `fk_user_roles_user_id_users`, `fk_user_roles_role_id_roles`, `pk_user_roles`, `pk_auth_identities`, `fk_auth_identities_user_id_users`, `uq_auth_identities_provider` — i.e., the names the naming convention installed in `feat_backend_002` should produce. |

## External REST tests — `test.sh` extensions

The existing external suite (`feat_testing_001`) hits the compose-brought-up backend. Add one flow:

| # | Case | Steps | Assertion |
|---|---|---|---|
| 1 | `/auth/me` requires a cookie (prod build, no mint) | `curl -sS -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/auth/me` | 401. |
| 2 | `/auth/logout` without a cookie | `curl -sS -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/api/v1/auth/logout` | 401. |

Mint-bearing flows belong in the pytest integration suite (where the test-only endpoint exists). `test.sh` runs against the default dev-compose build (ENV=dev) where the mint endpoint is absent by design.

## Boundary conditions

| Condition | Expected behavior |
|---|---|
| `SESSION_TTL_SECONDS=1` | Mint + immediate `/auth/me` succeed. `sleep 2` + `/auth/me` returns 401 and clears cookie. |
| `ADMIN_EMAILS=alice@x.com,,,` (empty fragments) | Parses to `{'alice@x.com'}` — empty fragments skipped. |
| `ADMIN_EMAILS` with 1000 entries | Parses once at startup into a frozenset; lookup is O(1). No perf test, but no linear scan. |
| `user_sessions:<uid>` set grows to 1000 entries | `revoke_all_for_user` still wipes all of them in one `DELETE *keys` call. |
| `email` column with very long address (300 chars) | `citext` column has no length cap; insert succeeds. `users.email` is `CITEXT NOT NULL UNIQUE`, not `VARCHAR`. |
| `provider_user_id` at max length (255 chars) | Accepted. 256 chars rejected by the column definition. |
| `role.name` max length (64 chars) | Accepted. 65 chars rejected. |
| Two simultaneous mint calls for a new user | Both succeed without duplicating the `users` row. The `find_or_create_user_for_test` helper uses an `INSERT ... ON CONFLICT (email) DO NOTHING RETURNING` pattern, then re-reads on conflict. |

## Security considerations

The design doc §8 table is the full posture. This test spec verifies the slice of it that 001 actually implements.

- **Cookie flags verified in response headers** — case 9 of `test_auth_me_logout.py`.
- **Session opaqueness** — `test_auth_sessions.py` case 1 asserts `len(session_id) == 64` and all hex. A weaker ID would fail that check.
- **Unauth precedes auth-z in dependency ordering** — `test_auth_dependencies.py` case 9. If `require_roles` were to 403 a request with no session (instead of 401), a scanner would learn that the route exists as a protected route.
- **`ADMIN_EMAILS` empty is a no-op** — `test_auth_bootstrap.py` case 1. Default `.env.example` ships `ADMIN_EMAILS=` so a fresh clone grants admin to nobody.
- **Test-only mint absent outside `env=test`** — `test_auth_test_mint_gating.py`. Defense-in-depth against a misconfigured deploy.
- **Malformed Redis payload does not leak** — `test_auth_middleware.py` case 4. The JSON decode exception is caught; the cookie is cleared; the request proceeds as unauthenticated. A corrupted Redis value is treated the same as a missing key.
- **Email uniqueness is case-insensitive** — `test_migration_0002_auth.py` case 3. Without `citext`, `Alice@X.com` and `alice@x.com` could create duplicate accounts that look distinct in the identity table — defeating the auto-link rule 002 and 003 depend on.
- **Session logs never contain raw IDs** — verified by the middleware tests (cases 3, 4, 5): the log event `auth.session.expired_cookie_cleared` carries `session_id_hash` not `session_id`.

## What is intentionally not tested

- **Real OTP or Google flow.** No code for it exists in 001. Tests for those land in `test_auth_002.md` and `test_auth_003.md`.
- **Frontend AuthContext or protected-route behavior.** Ships in `feat_frontend_002`.
- **`docs/design/auth-login-and-roles.md` content.** It is a committed design artifact; proofreading is part of PR review.
- **`conventions.md` §1 table format.** Covered transitively: if the table is malformed, the next spec session (Atlas reading conventions.md) will fail to parse the domains list, which surfaces as a visible review issue on the next PR.
- **Alembic `file_template` behavior.** Exercised the next time `alembic revision` is run; not a runtime code path.
- **Settings property `admin_emails_set` as a stand-alone unit.** Covered transitively by `test_auth_bootstrap.py` cases 1–5; no separate test.

## Regression surface

| Regression | What fails |
|---|---|
| `SessionMiddleware` moves above `RequestIDMiddleware` | `test_auth_middleware.py` case 6 (no `request_id` in log) |
| Session TTL not set or infinite | `test_auth_sessions.py` case 8 (TTL range check) |
| `require_roles` swaps 401/403 precedence | `test_auth_dependencies.py` case 9 |
| Bootstrap grants admin on every login (not just first) | `test_auth_bootstrap.py` case 7 (idempotent check) |
| `/auth/logout` tries Redis DEL with no session | `test_auth_me_logout.py` case 8 (no Redis command recorded) |
| Migration missing `ON DELETE CASCADE` | `test_migration_0002_auth.py` case 4 |
| Migration missing `citext` | `test_migration_0002_auth.py` case 3 |
| Test-mint endpoint leaks into prod | `test_auth_test_mint_gating.py` case 2 |
| Cookie missing `HttpOnly` | `test_auth_me_logout.py` case 9 |
| `revoke_sessions_for_user` misses reverse-index key | `test_auth_me_logout.py` case 6 (later mint accumulates stale IDs) |
