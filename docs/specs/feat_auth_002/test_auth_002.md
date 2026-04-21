# Test: Email OTP login

## Scope

This feature ships two new endpoints (`POST /api/v1/auth/otp/request`
and `POST /api/v1/auth/otp/verify`), the `EmailSender` abstraction with
two implementations, OTP helpers, a Redis-backed OTP store, and an
env-gated test fixture that makes the verify code deterministic. It
**removes** the `POST /api/v1/_test/session` endpoint introduced in
`feat_auth_001`.

Tests therefore:

1. Unit-test every helper (`otp.py`, `otp_store.py`, `email/console.py`,
   `email/resend.py`, `email/factory.py`) in isolation.
2. Integration-test the two endpoints end-to-end against a real
   Postgres + Redis, driven by the `TEST_OTP_*` fixture so verify is
   deterministic without log scraping.
3. Assert the deletion of the `_test/session` endpoint and the
   associated symbols (`test_router`, `TestSessionRequest`,
   `find_or_create_user_for_test`).
4. Rewrite the two 001 tests that relied on the old mint endpoint
   (`test_auth_middleware.py`, `test_auth_me_logout.py`) to mint via
   OTP.
5. Verify the `TEST_OTP_*` startup guard refuses to boot outside
   `env=test`.
6. Extend the external REST suite (`tests/tests/test_auth.py`) with
   two new scenarios: happy-path OTP login through compose, and
   wrong-code → 400.

Coverage of Google OAuth (§9.2 Google rows of the design doc) and
frontend login (§9.4) is **out of scope** — those land with `feat_auth_003`
and `feat_frontend_002`.

## New test files

### `backend/tests/test_auth_otp_helpers.py`

Unit tests for `backend/app/auth/otp.py`. Pure functions, no I/O.

| # | Case | Input | Expected output |
|---|---|---|---|
| 1 | `generate_code` length and alphabet | call 10 000 times | every result matches `^[0-9]{6}$` |
| 2 | `generate_code` uses `secrets.randbelow` | inspect module source via `inspect.getsource` | source references `secrets.randbelow`, not `random.` |
| 3 | `hash_code` / `verify_code` round-trip | `code="123456"` | `verify_code("123456", hash_code("123456")) is True` |
| 4 | `verify_code` mismatch | `code="000000"`, hash of `"123456"` | returns `False` |
| 5 | `verify_code` constant-time (smoke) | hash one code; verify 100× with correct then wrong code | both batches complete; timing difference under 20 ms across batches (sanity, not proof) |
| 6 | `email_hash` lowercases + trims | inputs `"Alice@X.com"`, `" alice@x.com "`, `"alice@x.com"` | all three produce the same hex string |
| 7 | `email_hash` output shape | any input | `re.match(r"^[0-9a-f]{64}$", result)` |
| 8 | `otp_key` | `"alice@x.com"` | `"otp:" + email_hash("alice@x.com")` |
| 9 | `rate_limit_keys` | `"alice@x.com"` | returns `(f"otp_rate:{h}:minute", f"otp_rate:{h}:hour")` |
| 10 | bcrypt work factor | inspect hash | `hash_code(code)[:7] == "$2b$10$"` (10 rounds) |

### `backend/tests/test_auth_otp_store.py`

Unit tests for `backend/app/auth/otp_store.py`. Uses the existing
`require_redis` fixture; skips when Redis is unreachable.

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 1 | `store_otp` + `load_otp` round-trip | Store with `code_hash="$2b$10$..."`, `ttl=600` | `load_otp` returns `OtpRecord(code_hash=..., attempts=0, created_at=...)`. `TTL otp:<h>` ∈ `[595, 600]`. |
| 2 | `load_otp` missing key | No store; random email | returns `None` |
| 3 | `load_otp` malformed payload | `SET otp:<h> "not json"` | returns `None`. No exception. |
| 4 | `load_otp` dict missing `code_hash` | `SET otp:<h> '{"attempts":0}'` | returns `None` |
| 5 | `increment_attempts_preserve_ttl` increments counter | Store with `attempts=0`, `ttl=600`; `sleep(0)`; call twice | `load_otp.attempts == 2`. TTL after second call within ±1 s of the first call's TTL. |
| 6 | `increment_attempts_preserve_ttl` on missing key | Never stored | returns 0; no key created. |
| 7 | `consume_otp` deletes the key | Store; consume | `GET otp:<h> -> None` |
| 8 | `check_and_increment_rate` first call allowed | `per_minute_limit=1`, `per_hour_limit=10` | `RateLimitResult(allowed=True, retry_after=0, window=None)`. `otp_rate:<h>:minute` exists with TTL ∈ `[55, 60]`. |
| 9 | Second call within the minute denies | As case 8, then immediate second call | `RateLimitResult(allowed=False, retry_after ∈ [1,60], window="minute")`. No new `otp:*` key would be written (caller's responsibility). |
| 10 | After minute TTL expires | Case 9, then `PEXPIRE otp_rate:<h>:minute 1` + wait | Third call `allowed=True`. |
| 11 | Hour limit enforced | `per_minute_limit=99`, `per_hour_limit=3`; call 4× rapidly | 4th returns `RateLimitResult(allowed=False, retry_after ∈ [1,3600], window="hour")`. |
| 12 | First-increment-only `EXPIRE NX` | Inspect with `PTTL` after 5 rapid calls | TTL counts down monotonically; does not reset to 60/3600 on later calls. |

### `backend/tests/test_auth_email_senders.py`

Unit tests for `ConsoleEmailSender` and `ResendEmailSender`.

**`ConsoleEmailSender`**:

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 1 | `send_otp` emits the console event | capture structlog with `structlog.testing.capture_logs()` | exactly one record with `event == "auth.email.console_otp_sent"`, `email_hash`, `code` fields populated; no `to` field leaks raw email |
| 2 | No `print()` calls | `capsys.readouterr()` | `captured.out == ""` and `captured.err == ""` |
| 3 | `email_hash` matches `otp.email_hash(to)` | vary `to` case | assertion holds across cases |

**`ResendEmailSender`** (using `httpx.MockTransport`):

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 4 | Happy path | mock returns `200 {"id": "em_abc"}` | one request: `POST https://api.resend.com/emails` with JSON body containing `from == settings.email_from`, `to == <email>`, `subject`, `text` (containing the code). `Authorization: Bearer <api_key>` header. |
| 5 | Non-2xx raises `EmailSendError` | mock returns `500 {"message": "oops"}` | `pytest.raises(EmailSendError)`; error carries `status_code == 500` and `detail == "oops"`. |
| 6 | Non-JSON 5xx | mock returns `502 "bad gateway"` (text) | `EmailSendError(status_code=502, detail=None)`. |
| 7 | Timeout surfaces as `EmailSendError` | mock raises `httpx.ReadTimeout` | `EmailSendError(status_code=None, detail="timeout")`. |
| 8 | Never logs API key | capture structlog across cases 4–7 | no log record contains the test API key substring. |
| 9 | Never logs OTP code | same capture | no log record under the ResendEmailSender module emits `code`. |
| 10 | `Protocol` conformance | `isinstance(sender, EmailSender)` | `True` for both `ConsoleEmailSender()` and `ResendEmailSender(...)` (requires `@runtime_checkable`). |

### `backend/tests/test_auth_email_factory.py`

Unit tests for `build_email_sender`.

| # | Case | Settings | Expected |
|---|---|---|---|
| 1 | Console path | `email_provider="console"` | returns `ConsoleEmailSender` instance |
| 2 | Resend happy path | `email_provider="resend"`, `resend_api_key="k"`, `email_from="x"` | returns `ResendEmailSender` instance with fields populated |
| 3 | Resend missing api key | `email_provider="resend"`, `resend_api_key=""` | raises `EmailProviderConfigError` with message mentioning `RESEND_API_KEY` |
| 4 | Resend missing from | `email_provider="resend"`, `email_from=""` | raises `EmailProviderConfigError` mentioning `EMAIL_FROM` |
| 5 | Unknown provider | `email_provider="sendgrid"` (Pydantic `Literal` should reject at Settings level, but factory guards anyway) | Settings instantiation raises; or, if bypassed by `model_construct`, factory raises `EmailProviderConfigError` |
| 6 | Startup guard: test-OTP set in dev | `env="dev"`, `test_otp_email="a"`, `test_otp_code="b"` | raises `EmailProviderConfigError` referencing `TEST_OTP_EMAIL`/`TEST_OTP_CODE` |
| 7 | Startup guard: test-OTP set in prod | `env="prod"`, `test_otp_email="a"`, `test_otp_code="b"` | raises `EmailProviderConfigError` |
| 8 | Startup guard: test-OTP partial in test | `env="test"`, `test_otp_email="a"`, `test_otp_code=""` | does **not** raise (gating requires both; partial is a no-op, treated as off) |
| 9 | Startup guard: test-OTP both empty in non-test | `env="dev"`, both empty | does not raise |
| 10 | Startup guard: test-OTP both set in test | `env="test"`, both non-empty | does not raise |

### `backend/tests/test_auth_otp_request.py`

Endpoint tests for `POST /api/v1/auth/otp/request`. Real Postgres +
Redis via `require_db` / `require_redis`. The email sender is
**monkeypatched** on `app.state.email_sender` to a spy that records
calls — the factory still builds the real console sender at startup,
but the test replaces it so send failures can be simulated.

| # | Case | Arrangement | Assertion |
|---|---|---|---|
| 1 | Happy path — console | fresh Redis; `email_provider="console"`; POST `{email: "alice@x.com"}` | 204. Spy recorded one call `send_otp(to="alice@x.com", code="NNNNNN")`. Redis has `otp:<h>` with `attempts=0`, TTL ∈ `[595, 600]`. One log event `auth.otp.requested` with `provider="console"`. |
| 2 | Same response for unknown email | POST `{email: "never-registered@x.com"}` | 204. Spy recorded one call. `otp:<h>` stored. No DB read for users. |
| 3 | Rate limit denies second request within 60 s | Two POSTs back-to-back | first 204; second 429 body `{"detail": "too_many_requests", "retry_after": <int>}`, header `Retry-After: <same int>`. Log event `auth.otp.rate_limited` with `window="minute"`. |
| 4 | Rate limit hour window | `per_minute_limit=99`, `per_hour_limit=3`, 4 requests | 4th returns 429 with `window="hour"`. |
| 5 | Email-shape validation | POST `{email: "not-an-email"}` | 400 or 422 (whichever the schema produces by default; assert it's a 4xx, not 5xx; this input is invalid before the shape-normalization path). |
| 6 | `extra="forbid"` | POST `{email: "a@b.c", foo: "bar"}` | 422 (Pydantic). Not this feature's core concern; asserts the model config stays strict. |
| 7 | Resend 500 still 204 | `email_provider="resend"`, MockTransport returns 500 | response 204. Log event `auth.otp.send_failed` with `reason="http_error"` and `http_status=500`. Redis `otp:<h>` still present. |
| 8 | Resend timeout still 204 | MockTransport raises `ReadTimeout` | 204. Log event `auth.otp.send_failed` with `reason="timeout"`. |
| 9 | Store-then-send ordering | Replace the spy to raise after recording — but the `auth.otp.send_failed` path must still observe a stored OTP | After the call, `otp:<h>` is present. Verify step (a subsequent `/verify` test in `test_auth_otp_verify.py`) can succeed. |
| 10 | Case-insensitive email key | POST `{email: "Alice@X.com"}`, then POST `{email: "alice@x.com"}` | Second call denied by rate limit because both normalize to the same hash. |
| 11 | Zero DB writes | Wrap the call in a SQLAlchemy query-recording context | Recorded list is empty. |
| 12 | Email is not in the response body | inspect body bytes | empty body (204). |

### `backend/tests/test_auth_otp_verify.py`

Endpoint tests for `POST /api/v1/auth/otp/verify`. Uses the test-OTP
fixture with `TEST_OTP_EMAIL="alice@x.com"`, `TEST_OTP_CODE="123456"`,
`ENV=test` so the verify code is deterministic.

| # | Case | Flow | Assertion |
|---|---|---|---|
| 1 | Happy path new user | POST `/otp/request {email: alice@x.com}`; POST `/otp/verify {email: alice@x.com, code: 123456}` | 200. `Set-Cookie` contains `session=<64 hex>; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`. Body is `MeResponse(user_id, email: 'alice@x.com', display_name: None, roles: ['user'])`. One `users` row and one `auth_identities` row (`provider='email'`). One `user_roles` row granting `user`. Log events: `auth.otp.verified new_user=true`, `auth.session.created`. |
| 2 | `/me` round-trip after verify | case 1 cookie | `GET /auth/me` returns same `MeResponse`. |
| 3 | Wrong code → 400 uniform body | request; verify with `code="999999"` | 400 body `{"detail": "invalid_or_expired_code"}`. Redis `otp:<h>` still present, `attempts=1`. Log event `auth.otp.failed reason=wrong_code attempts=1`. |
| 4 | Five wrong codes then correct code locked | request; verify wrong ×5; verify correct | 6th call returns 400 same body. Redis `otp:<h>` now deleted (one-shot lockout). Log event `auth.otp.failed reason=attempts_exhausted`. |
| 5 | One-shot on success | request; verify correct; verify correct again | second verify returns 400 `invalid_or_expired_code`. |
| 6 | Never-requested email | `ENV=test`, fixture set; verify `{email: bob@x.com, code: 123456}` | 400 body identical to wrong-code. Log event `auth.otp.failed reason=missing`. |
| 7 | Expired OTP | request; `DEL otp:<h>` manually to simulate TTL expiry; verify correct code | 400 `invalid_or_expired_code`. |
| 8 | Non-six-digit code rejected as invalid_or_expired_code, not 422 | request; verify `{code: "1234"}` | 400 (not 422) with body `{"detail": "invalid_or_expired_code"}`. Route-level mapping is working. |
| 9 | Non-digit code | verify `{code: "abcdef"}` | 400 `invalid_or_expired_code`. |
| 10 | Case-insensitive email on verify | request with `{email: Alice@X.com}`; verify with `{email: alice@x.com, code: 123456}` | 200. Same `users` row (CITEXT). |
| 11 | Auto-link existing user | Seed `users(alice@x.com)` directly via SQL; no pre-existing `auth_identities` row; request + verify | 200. Now exactly one `auth_identities(provider='email', provider_user_id='alice@x.com')` row. No duplicate `users` row. |
| 12 | Reuse existing email-identity | Seed `users` + `auth_identities(email, alice@x.com, ...)`; request + verify | 200. No new `users` row, no new `auth_identities` row. |
| 13 | `ADMIN_EMAILS` bootstrap on first login | `ADMIN_EMAILS="alice@x.com"`; new user flow | `MeResponse.roles == ["admin", "user"]` (sorted). `user_roles` has two rows. |
| 14 | Second login does not duplicate roles | case 13, then a second request+verify for the same email (after rate-limit reset) | Still exactly two `user_roles` rows. Idempotent. |
| 15 | Zero DB writes on /request path, DB writes only on /verify | Query-recorder around both calls | `/request` records zero. `/verify` records the expected find-or-create + identity inserts. |
| 16 | Cookie Secure attribute reflects settings | verify with `SESSION_COOKIE_SECURE=true` | `Set-Cookie` contains `Secure`. With `false` (default), does not. |
| 17 | Concurrent verify for a new email does not duplicate | fire two `/verify` calls in parallel for a new email with the test code | both succeed OR one 400s after the other consumed the OTP — either way, `users` has one row, `auth_identities` has one row. |
| 18 | Verify failure does not create a user | request; verify wrong code | `users` row count unchanged. |
| 19 | `_test/session` is gone | `POST /api/v1/_test/session` under `ENV=test` | 404 (endpoint deleted). |
| 20 | Symbols deleted | `pytest.raises(ImportError)` on `from app.auth.schemas import TestSessionRequest`, `from app.auth.service import find_or_create_user_for_test`, `from app.auth.router import test_router` | all three raise. |

### `backend/tests/test_auth_test_otp_fixture.py`

Dedicated tests for the `TEST_OTP_EMAIL` / `TEST_OTP_CODE` env-gated
affordance.

| # | Case | Settings | Flow | Expected |
|---|---|---|---|---|
| 1 | Fixture active overwrites stored hash | `env=test`, both set, email matches | request, then inspect `otp:<h>.code_hash` | `verify_code(settings.test_otp_code, code_hash) is True` |
| 2 | Fixture active, email does not match | `env=test`, both set, request for a different email | inspect stored hash | Hash is the **real** generated code's hash; test code does not verify. |
| 3 | Fixture off in `env=test` when either var empty | `env=test`, `test_otp_email="x"`, `test_otp_code=""` | request for `x` | real generated code is stored; test code does not verify. |
| 4 | Fixture off in `env=dev` even when both set would be refused at startup | separate subtest: `create_app(Settings(env="dev", test_otp_email="x", test_otp_code="y"))` | — | raises `EmailProviderConfigError` during lifespan startup (factory guard). |
| 5 | Test-OTP path does not bypass rate limit | fixture active; two requests within 60 s | second is 429, regardless of fixture | |
| 6 | Console sender still logs a decoy | fixture active; grab captured logs | `auth.email.console_otp_sent` event fired with `code` equal to the **generated** code, not the test code (intentional — so a human tailing logs cannot shortcut their way into the test account). |
| 7 | Verify code matches fixture, not generated | fixture active; request; verify with `settings.test_otp_code` | 200 |
| 8 | Verify code matches generated does NOT succeed | fixture active; request; scrape generated code from log; verify with that | 400 `invalid_or_expired_code` (because the hash was overwritten). |
| 9 | `grep test_otp_ backend/app/` hits exactly three locations | walk the tree with `ast` | exactly: `settings.py` field definitions, `router.py` request handler branch, `email/factory.py` startup guard |

Case 9 is a repo-hygiene assertion — it makes sure future contributors
cannot sneak a fourth use of `test_otp_*` into production code without
the test tripping.

### Rewrites of 001 test files

#### `backend/tests/test_auth_middleware.py` (rewrite)

The six cases of 001's middleware tests are preserved. Only the
cookie-minting step changes.

| # | Case | Change from 001 | Assertion (unchanged) |
|---|---|---|---|
| 1 | Public endpoint, no cookie | unchanged | 200, no `Set-Cookie` |
| 2 | Valid cookie populates context | Mint via `/otp/request` + `/otp/verify` (fixture) instead of `/_test/session` | 200, body echoes `roles` |
| 3 | Expired session clears cookie | Mint via OTP; `DEL session:<id>`; call `/me` | 401, cookie cleared, log event `auth.session.expired_cookie_cleared reason=missing_key` |
| 4 | Malformed payload clears cookie | Mint via OTP; overwrite session value with `b"not json"`; call `/me` | 401, cookie cleared, reason=`malformed_payload` |
| 5 | Malformed cookie shape | Send arbitrary 60-hex cookie | 401, cookie cleared, reason=`malformed_cookie` |
| 6 | Middleware runs after RequestID | Inspect case 3 log | carries `request_id` |

#### `backend/tests/test_auth_me_logout.py` (rewrite)

001's nine cases, all preserved. The "mint" step is replaced with the
OTP flow.

| # | Case | Change | Assertion (unchanged) |
|---|---|---|---|
| 1 | Happy path mint → `/me` → logout → `/me` | mint via OTP | as in 001 |
| 2 | ADMIN_EMAILS bootstrap | mint via OTP | roles contains `admin` and `user` |
| 3 | Non-bootstrap user | mint via OTP | roles exactly `["user"]` |
| 4 | Extra roles parameter | **deleted** — `TestSessionRequest.roles` no longer exists | — |
| 5 | Idempotent mint | Two OTP cycles for the same email | `users` has one row; now **one** `auth_identities` row (001 had zero because the mint path skipped identities). |
| 6 | `revoke_sessions_for_user` end-to-end | two OTP cycles (separate requests, rate-limit-spaced) → revoke | both sessions 401 afterwards |
| 7 | No cookie → 401 | unchanged | 401 |
| 8 | Logout without session | unchanged | 401; no Redis delete command recorded |
| 9 | Cookie attributes | inspect cookie set by `/otp/verify` | `HttpOnly; SameSite=Lax; Path=/; Max-Age=86400`; `Secure` only when settings say so |

Case 4 being deleted is intentional: the removed `roles` field on the
request body was a mint-endpoint convenience. Real login paths do not
accept caller-specified roles. Test spec reflects reality.

### `backend/tests/test_migration_0002_auth.py` (unchanged from 001)

002 adds no migration, so 001's migration test file is **not edited**.

## External REST tests — `test.sh` extensions

Two new scenarios added to `tests/tests/test_auth.py`, using a new
scoped `otp_fixture` fixture that sets `TEST_OTP_EMAIL` / `TEST_OTP_CODE`
via the compose-side `.env` overlay.

**Setup requirement.** The compose stack must be brought up with the
two test vars set in `infra/.env`. The `test.sh` flow is unchanged;
what changes is that the CI/local operator running `./test.sh` must
either:

- Set `TEST_OTP_EMAIL` + `TEST_OTP_CODE` in `infra/.env` before `make up`, or
- Use a `docker compose override` file that the external-test suite
  brings in (Vulcan's call; either is acceptable).

The spec documents this and the test file skips gracefully with a
clear reason when the vars are unset on the live backend (probed via
an introspection endpoint? — **no, that would add a prod surface**;
instead, the skip is conditional on the suite-side `TEST_OTP_EMAIL` /
`TEST_OTP_CODE` env vars being set at `test.sh` launch time, mirroring
the backend's settings).

Existing 001 assertions stay:

| # | Case | Steps | Assertion |
|---|---|---|---|
| 1 | `/auth/me` requires a cookie | GET with no cookie | 401 |
| 2 | `/auth/logout` without a cookie | POST with no cookie | 401 |

New 002 assertions:

| # | Case | Steps | Assertion |
|---|---|---|---|
| 3 | OTP happy path | POST `/otp/request` for `TEST_OTP_EMAIL`; POST `/otp/verify` with `TEST_OTP_CODE`; GET `/me` | request 204, verify 200 + Set-Cookie, `/me` 200 with email matching `TEST_OTP_EMAIL` |
| 4 | OTP wrong code | POST `/otp/request`; POST `/otp/verify` with `"999999"` | verify 400 body `{"error":{"message":"invalid_or_expired_code", ...}}` (envelope shape from `feat_backend_002`) |

Scenarios 3–4 are skipped when the live backend's env does not have
the fixture set — detected by a single discovery POST that records the
result and short-circuits subsequent assertions.

## Boundary conditions

| Condition | Expected behavior |
|---|---|
| `OTP_CODE_TTL_SECONDS=1` | Mint + immediate verify succeeds. `sleep 2` + verify fails 400 (expired). |
| `OTP_MAX_ATTEMPTS=1` | First wrong code → 400; second call (even with correct code) → 400 (attempts exhausted on first wrong). |
| `OTP_RATE_PER_MINUTE=0` | Every request 429 (minute counter starts at 1, exceeds 0 immediately). |
| `OTP_RATE_PER_HOUR=0` | Same — every request 429. |
| `EMAIL_PROVIDER_TIMEOUT_SECONDS=0.001` | Resend path reliably times out → `EmailSendError(timeout)`; response 204 unchanged. |
| `RESEND_API_KEY=""` + `EMAIL_PROVIDER=resend` | Factory raises `EmailProviderConfigError` on app startup. `make up` fails loudly. |
| Email with 300 characters | Accepted by shape check (only requires `@` and length ≥ 3). `CITEXT` column has no length cap. |
| Email with leading/trailing whitespace | Stripped by `_validate_email_shape`; hash is the stripped form. |
| Email differing only in case | Same `otp_key`, same `users` row thanks to `CITEXT`. |
| Code with leading zeros ("012345") | bcrypt preserves the string bytes; hash and verify round-trip. |
| Code exactly "000000" / "999999" | Acceptable inputs; no special-case. |
| `TEST_OTP_CODE="abcdef"` (non-digit) | Verify-side shape check still requires 6 digits. Trying to verify with the fixture code → 400. Effectively disables the fixture without a startup error. Documented as "operator footgun; set a numeric test code." |
| `TEST_OTP_CODE` with leading/trailing whitespace | The fixture comparison trims on both sides (mirrors `_validate_email_shape` trim behavior), so padded values work. |
| `TEST_OTP_EMAIL="ALICE@X.COM"` | Case-insensitive match on the inbound request; overwrite applies. |
| Concurrent `/request` and `/verify` for the same email | Rate limit spans both endpoints? **No** — rate limit applies only to `/request`. `/verify` has no rate limit of its own but is gated by `OTP_MAX_ATTEMPTS`. |
| Redis down during `/verify` | Exception bubbles up to the exception envelope → 500 `internal_error`. Not a user-facing path. |
| Postgres down during `/verify` | Same. Exception envelope → 500. |

## Security considerations

The design doc §8 posture table is the full picture. This test spec
verifies the slice of it that 002 actually implements.

- **Account enumeration parity** — `test_auth_otp_request.py` case 2
  asserts identical response for known and unknown emails, no DB
  read on `/request`.
- **Bad-code uniformity** — `test_auth_otp_verify.py` cases 3, 6, 7, 8
  all assert body `{"detail": "invalid_or_expired_code"}` and HTTP
  400. Missing, expired, wrong, and exhausted all indistinguishable.
- **Rate-limit applies across case** — `test_auth_otp_request.py`
  case 10.
- **One-shot on success** — `test_auth_otp_verify.py` case 5.
- **Attempt exhaustion lockout** — case 4.
- **OTP stored as bcrypt hash** — `test_auth_otp_helpers.py` case 10
  checks the `$2b$10$` prefix; `test_auth_otp_store.py` stores and
  retrieves the hashed form.
- **API key never logged** — `test_auth_email_senders.py` case 8.
- **Code only in dev log event** — `test_auth_test_otp_fixture.py`
  case 6 (console event) and `test_auth_email_senders.py` case 9
  (no code in Resend path).
- **Test-OTP fixture cannot run in prod** — `test_auth_email_factory.py`
  cases 6–7; `test_auth_test_otp_fixture.py` case 4.
- **Cookie flags on verify** — `test_auth_otp_verify.py` case 16,
  plus `test_auth_me_logout.py` (rewrite) case 9.
- **Session hashing in logs** — the session-creation log event
  (`auth.session.created`) uses `session_id_hash`, not raw ID;
  verified by inspecting captured logs in
  `test_auth_otp_verify.py` case 1.

## What is intentionally not tested

- **Google OAuth.** No code for it exists in 002.
- **Frontend OTP form.** `feat_frontend_002`.
- **`last_login_at` / `last_used_at`.** Columns do not exist; design-
  doc steps that would update them are documented no-ops per
  `design_auth_002.md` "Deviations".
- **`is_active=false` branch.** Column does not exist; the `403
  account_disabled` failure mode is unreachable.
- **Multi-provider email fallback.** Single provider at a time.
- **Resend webhooks.** Future ops feature.
- **Email rendering / HTML templating.** Body is a plain-text string.
- **OTP code uniqueness across users.** Two users in different
  requests can legally get the same six-digit code; the lookup is by
  email hash, not code.
- **Concurrent rate-limit writes.** The `EXPIRE ... NX` semantics
  handle this correctly per Redis; retesting Redis's own atomicity is
  out of scope.
- **Alembic migration file.** None added.
- **`conventions.md`.** Not modified by this feature.

## Regression surface

| Regression | What fails |
|---|---|
| `/request` response body differs between known and unknown email | `test_auth_otp_request.py` case 2 |
| `/verify` bad-code conditions leak distinguishing information | `test_auth_otp_verify.py` cases 3, 6, 7, 8 (same-body assertion) |
| OTP code stored in plaintext | `test_auth_otp_store.py` case 1 (asserts `code_hash` is bcrypt) |
| Rate limit reset on every increment | `test_auth_otp_store.py` case 12 |
| Test-OTP fixture leaks into dev/prod | `test_auth_email_factory.py` cases 6–7; `test_auth_test_otp_fixture.py` case 4 |
| Removing the `/_test/session` endpoint accidentally kept in the tree | `test_auth_otp_verify.py` case 19 + case 20 |
| Verify shape validation returns 422 instead of 400 | `test_auth_otp_verify.py` cases 8–9 |
| Session cookie missing `HttpOnly` | `test_auth_otp_verify.py` case 16 |
| Verify's one-shot semantic regresses | `test_auth_otp_verify.py` case 5 |
| Attempts lockout not consumed on 6th call | `test_auth_otp_verify.py` case 4 |
| Resend API key logged | `test_auth_email_senders.py` case 8 |
| Settings field `test_otp_email` has a compiled-in default | `test_auth_email_factory.py` case 9 (empty-empty default) + `grep` hygiene in `test_auth_test_otp_fixture.py` case 9 |
| Email sender is `print`-based instead of structlog | `test_auth_email_senders.py` case 2 |
| `TEST_OTP_*` fixture also skips rate limit | `test_auth_test_otp_fixture.py` case 5 |
| Symbols `TestSessionRequest`, `find_or_create_user_for_test`, `test_router` survive | `test_auth_otp_verify.py` case 20 |
