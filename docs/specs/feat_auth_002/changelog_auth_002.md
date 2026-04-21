# Changelog: feat_auth_002 (email OTP login)

## Added

- `POST /api/v1/auth/otp/request` -- takes `{email}`, mints and stores
  a 6-digit OTP (bcrypt-hashed, 10-minute TTL), delivers through the
  configured `EmailSender`, rate-limits 1/minute and 10/hour per email
  by default. Returns 204 on every success and on provider failure;
  429 with `Retry-After` on rate-limit deny. Never reads the database.
- `POST /api/v1/auth/otp/verify` -- takes `{email, code}`, checks the
  bcrypt hash against the stored record, enforces a 5-attempt lockout,
  one-shot on success, resolves the caller to a `users` + `auth_identities`
  row (find-or-create with `ADMIN_EMAILS` bootstrap), mints a session,
  and sets the `session=...` cookie with the same attributes the
  session machinery in feat_auth_001 already uses.
- `backend/app/auth/email/` package with a runtime-checkable
  `EmailSender` Protocol, a `ConsoleEmailSender` that logs the OTP via
  `structlog`, and a `ResendEmailSender` that POSTs to
  `https://api.resend.com/emails` through `httpx.AsyncClient`. A
  `build_email_sender(Settings)` factory dispatches on
  `EMAIL_PROVIDER` and validates configuration at lifespan startup.
- `backend/app/auth/otp.py` -- pure helpers (`generate_code`,
  `hash_code`, `verify_code`, `email_hash`, `otp_key`,
  `rate_limit_keys`). Uses `secrets.randbelow` (not `random.*`);
  pinned bcrypt work factor of 10.
- `backend/app/auth/otp_store.py` -- Redis-backed storage with
  `OtpRecord`, `RateLimitResult`, `store_otp`, `load_otp`,
  `increment_attempts_preserve_ttl` (atomic server-side Lua),
  `consume_otp`, `check_and_increment_rate` (pipelined
  `INCR`/`EXPIRE ... NX`).
- Ten new `Settings` fields under `# ---- Email / OTP (feat_auth_002) ----`:
  `email_provider`, `email_from`, `email_provider_timeout_seconds`,
  `resend_api_key`, `otp_code_ttl_seconds`, `otp_max_attempts`,
  `otp_rate_per_minute`, `otp_rate_per_hour`, `test_otp_email`,
  `test_otp_code`.
- Two `.env` blocks in `infra/.env.example`: Email / OTP settings with
  dev defaults, plus an intentionally-empty test-OTP fixture block
  with a multi-line comment warning operators that the fixture must
  stay empty in non-test environments.
- `docs/deployment/README.md` + `docs/deployment/email-otp-setup.md` --
  a landing page and full Resend setup guide (provider comparison,
  dev console flow with `docker compose logs` snippet, domain DKIM/SPF
  verification, API-key generation, troubleshooting table, credential
  rotation, test-OTP fixture reminder).
- Seven new backend test modules covering the pure helpers, Redis
  store, both sender implementations, the factory, both endpoints,
  and the test-OTP fixture (including a grep-hygiene assertion that
  pins the fixture reference count at exactly three source files).
- Two new external-REST scenarios in `tests/tests/test_auth.py`:
  happy-path OTP login and wrong-code -> 400, both gated on the
  suite-side `TEST_OTP_EMAIL` / `TEST_OTP_CODE` env vars.
- `bcrypt>=4.1` added to `[project] dependencies` in
  `backend/pyproject.toml`.

## Changed

- `backend/app/main.py` lifespan builds `app.state.email_sender` at
  startup; the factory's `EmailProviderConfigError` surfaces
  loudly if `EMAIL_PROVIDER=resend` is set without a `RESEND_API_KEY`
  (or without `EMAIL_FROM`), and if `TEST_OTP_EMAIL` / `TEST_OTP_CODE`
  are populated outside `ENV=test`.
- `backend/app/auth/schemas.py` now exports `OtpRequestIn` and
  `OtpVerifyIn`. The shared `_validate_email_shape` helper is
  reused.
- `backend/app/auth/service.py` now exports
  `find_or_create_user_for_otp` (returning `(user, role_names,
  new_user)`).
- `backend/tests/test_auth_middleware.py` and
  `backend/tests/test_auth_me_logout.py` rewritten to mint sessions
  through the OTP flow using the `TEST_OTP_EMAIL` / `TEST_OTP_CODE`
  fixture instead of the removed `_test/session` endpoint. The
  extra-roles case from 001 is deleted intentionally (the real login
  path does not accept caller-specified roles).
- `backend/pyproject.toml`: `httpx` promoted from the `[dependency-
  groups] dev` list to the main `dependencies` list since it is no
  longer dev-only at runtime (used by `ResendEmailSender`). The dev
  group now contains `pytest` and `pytest-asyncio` only.
- `docs/tracking/features.md` and `docs/specs/README.md` advance
  `feat_auth_002` from `Ready` to `In Build` as part of this work.

## Removed

- `POST /api/v1/_test/session` endpoint (the entire env-gated
  `test_router` and its `mint_test_session` handler).
- `app.auth.schemas.TestSessionRequest` class.
- `app.auth.service.find_or_create_user_for_test` function.
- The `if resolved.env == "test": ... include_router(test_router, ...)`
  block in `backend/app/main.py`.
- `backend/tests/test_auth_test_mint_gating.py` (the endpoint it
  covered is gone).

## Security

- OTP codes are bcrypt-hashed at rest; the raw code exists in memory
  only for the duration of the request handler and in the
  `ConsoleEmailSender` log line (intentional dev-only exception).
- `/otp/request` returns the same 204 response and same log event for
  known and unknown emails -- no database read happens on request.
- `/otp/verify` returns the same `{"error": {"message":
  "invalid_or_expired_code", ...}}` envelope body and HTTP 400 for
  missing, expired, wrong, exhausted, and shape-invalid requests.
  Structured logs distinguish the four reasons for operators.
- Rate limits are per-email-hash (1/min, 10/hour by default);
  `EXPIRE ... NX` pins the window to the first request of the window,
  not the most recent.
- `ResendEmailSender` never logs the API key, the recipient, or the
  OTP code. `ConsoleEmailSender` logs the code (dev convenience) but
  its event name includes `console` so an accidental production use
  is greppable.
- `TEST_OTP_EMAIL` / `TEST_OTP_CODE` must stay empty outside
  `ENV=test`; the factory refuses to build the email sender
  otherwise, failing `make up` loudly.

## Deferred (called out in the design spec, not in scope for 002)

- `last_login_at` column on `users`, `last_used_at` column on
  `auth_identities`, `is_active` column on `users`. A future backend
  feature can add them additively.
- Google OAuth endpoints (`feat_auth_003`).
- Login UI (`feat_frontend_002`).
- Resend bounce/complaint webhooks.
- Email HTML templates.
