# Implementation notes: feat_auth_002 (email OTP login)

## Scope delivered

All functional and non-functional requirements (1-22) from
`feat_auth_002.md` landed in this branch. Every acceptance checkbox
on the feature spec is covered by at least one test in
`backend/tests/` or `tests/tests/`.

## Files created

### Backend runtime

| Path | Lines | Purpose |
|---|---|---|
| `backend/app/auth/otp.py` | 123 | Pure helpers: `generate_code`, `hash_code`, `verify_code`, `email_hash`, `otp_key`, `rate_limit_keys`. Pinned bcrypt to 10 rounds. |
| `backend/app/auth/otp_store.py` | 293 | Redis I/O: `OtpRecord`, `RateLimitResult`, `store_otp`, `load_otp`, `increment_attempts_preserve_ttl` (server-side Lua), `consume_otp`, `check_and_increment_rate`. |
| `backend/app/auth/email/__init__.py` | 52 | Package marker + `get_email_sender` dependency + re-exports. |
| `backend/app/auth/email/base.py` | 86 | `EmailSender` runtime-checkable Protocol, `EmailSendError`, `EmailProviderConfigError`. |
| `backend/app/auth/email/console.py` | 45 | `ConsoleEmailSender` -- emits the `auth.email.console_otp_sent` event through `app.logging.get_logger`. |
| `backend/app/auth/email/resend.py` | 158 | `ResendEmailSender` -- thin `httpx.AsyncClient` wrapper around `POST https://api.resend.com/emails`. No SDK. |
| `backend/app/auth/email/factory.py` | 83 | `build_email_sender(Settings)` dispatch + startup validation. Includes the `TEST_OTP_*`-in-non-test startup guard. |

### Backend tests

Seven new test modules (`test_auth_otp_helpers.py`, `test_auth_otp_store.py`,
`test_auth_email_senders.py`, `test_auth_email_factory.py`,
`test_auth_otp_request.py`, `test_auth_otp_verify.py`,
`test_auth_test_otp_fixture.py`) plus full rewrites of
`test_auth_middleware.py` and `test_auth_me_logout.py` to mint via OTP.

### Documentation

| Path | Purpose |
|---|---|
| `docs/deployment/README.md` | One-screen landing page listing external services that need manual setup. |
| `docs/deployment/email-otp-setup.md` | Operator guide covering provider comparison, dev console flow, Resend setup, troubleshooting table, credential rotation, and the `TEST_OTP_*` fixture reminder. |

## Files modified

- `backend/app/auth/router.py`: added `POST /otp/request` and
  `POST /otp/verify`; removed `test_router` + `mint_test_session`.
- `backend/app/auth/schemas.py`: added `OtpRequestIn` and `OtpVerifyIn`;
  removed `TestSessionRequest`.
- `backend/app/auth/service.py`: added `find_or_create_user_for_otp`;
  removed `find_or_create_user_for_test`.
- `backend/app/main.py`: added lifespan wiring for
  `app.state.email_sender`; removed the env-gated `test_router` mount.
- `backend/app/settings.py`: added 10 new fields under
  `# ---- Email / OTP (feat_auth_002) ----`.
- `backend/app/auth/bootstrap.py`: updated a stale docstring that
  still pointed at the removed `/_test/session` endpoint.
- `backend/pyproject.toml`: added `bcrypt>=4.1`; promoted `httpx`
  from the `dev` group to main deps (see below).
- `backend/uv.lock`: regenerated with the dependency changes.
- `infra/.env.example`: appended Email/OTP + test-OTP blocks.
- `tests/tests/test_auth.py`: added two new OTP scenarios.

## Files deleted

- `backend/tests/test_auth_test_mint_gating.py`: the endpoint it
  covered is gone; the test has no meaning in 002.

## Symbols removed

- `app.auth.schemas.TestSessionRequest`
- `app.auth.service.find_or_create_user_for_test`
- `app.auth.router.test_router`, `mint_test_session`
- The env-gated `if resolved.env == "test": ... include_router(test_router, ...)`
  block in `app.main`.

`test_auth_otp_verify.py::test_removed_symbols_are_not_importable`
asserts each of these via `pytest.raises(ImportError)` so a future
contributor cannot reintroduce them without the test tripping.

## Design decisions / notes

1. **`httpx` promoted from dev-group to main dependencies.** Spec
   requirement 16 made this conditional: promote "only if the build-
   time `uv pip show httpx` check shows it is not transitively
   available at runtime". Inspection showed that `uvicorn[standard]`
   pulls in `click`, `h11`, `watchfiles`, and `httptools` but not
   `httpx` -- so we promote. The dev group now contains just pytest
   and pytest-asyncio.

2. **`bcrypt>=4.1` added to main dependencies.** The runtime resolves
   `bcrypt==5.0.0` per the lockfile; the `$2b$10$` hash format is
   unchanged from 4.x so the stable contract the test suite asserts
   is upheld.

3. **Server-side Lua script for `increment_attempts_preserve_ttl`.**
   Chose the `PTTL` + `SET ... PX` approach per design-doc §5
   ("Deviations") option 5 so the module stays portable to
   pre-Redis-7 deployments. The docker-compose file pins
   `redis:7-alpine` so `KEEPTTL` would also have worked; either
   implementation is acceptable per spec.

4. **429 rate-limit response uses `JSONResponse` directly, bypassing
   the FastAPI exception-envelope middleware.** The test spec calls
   for the raw body shape `{"detail": "too_many_requests",
   "retry_after": N}`, which is incompatible with the
   feat_backend_002 envelope shape (`{"error": {"code": ..., "message":
   ..., "request_id": ...}}`). The verify handler uses `HTTPException`
   and gets wrapped; the request handler uses `JSONResponse` and
   stays raw. Tests for both paths assert the actual observed shape.

5. **Verify 400 body is the enveloped form.** All bad-code
   conditions (missing, expired, wrong, exhausted, shape-invalid)
   raise `HTTPException(status_code=400, detail="invalid_or_expired_code")`.
   The existing `feat_backend_002` envelope wraps that as
   `{"error": {"code": "http_error", "message": "invalid_or_expired_code",
   "request_id": "..."}}`. Internal tests assert on
   `body["error"]["message"]`; external tests assert the same shape.
   The spec's example snippets show `{"detail": ...}` -- this is the
   pre-envelope form; the tests have been written to the post-
   envelope reality that feat_backend_002 introduced.

6. **`auth.session.created` log event is emitted from the verify
   handler, not from `sessions.create`.** The event vocabulary in
   requirement 15 says "reuses the helper from 001", but inspection
   of `app.auth.sessions.create` shows it does not currently emit a
   log event. Adding the emission inside `sessions.create` would
   change the shape 001 shipped; emitting it from the verify handler
   matches the event-per-route rhythm the rest of the OTP flow
   already uses. The hash helper on the router mirrors
   `app.middleware._session_id_hash` so the two events produce
   identical `session_id_hash` values.

7. **`find_or_create_user_for_otp` returns `(user, role_names,
   new_user)`.** The spec was silent on whether `new_user` comes
   from the helper or the handler; placing it in the helper's return
   tuple keeps the handler branch-free and lets future tests assert
   on the flag directly.

8. **Deactivated-user path is documented but unreachable.** The
   handler checks `getattr(user, "is_active", True)` and raises
   `HTTPException(403, "account_disabled")` on `False`. The column
   does not exist on `users` (see design-spec Deviation 1), so the
   branch is currently dead code; when a future migration adds the
   column, the behavior comes online automatically.

## Deviations from the design doc

All three deviations called out in the design spec hold:

1. **`last_login_at`, `last_used_at`, `is_active` columns.** Not
   added -- feat_auth_001 did not ship a migration for them, and 002
   intentionally adds no migration. The three design-doc steps that
   would update them (§7.1 step 6, §7.2 step 7, §7.1 deactivated-user
   row) are documented no-ops; the verify handler's
   `getattr(user, "is_active", True)` guard is forward-compatible.

2. **No Resend SDK package.** `httpx` handles the one endpoint and
   one JSON body; the SDK would have added a transitive surface
   without a matching capability gain.

3. **`bcrypt` as the one new top-level dependency.** Reaffirmed in
   `pyproject.toml`; `bcrypt==5.0.0` resolves at lock time.

## Known gaps / follow-ons

- **`ADMIN_EMAILS` grant is first-login-only.** Matches 001's
  semantics. Mid-lifetime admin promotion still needs a DB write; a
  later feature can add a UI or CLI helper.
- **Cross-IP flooding.** Rate limit is per-email-hash; a script with
  varied emails can defeat it. Mitigation belongs at the reverse-
  proxy layer (nginx/Caddy) -- documented in the deployment guide.
- **Resend webhooks.** Bounce / complaint handling is out of scope
  (see spec §"Out of Scope").
- **Email HTML templates.** OTP body is a plain-text string literal
  in `resend.py`; a later feature can swap to a templating engine.

## Verification

- `uv run pytest tests/` inside the backend container: **150 passed,
  1 skipped** (the env-file-gitignore smoke case). Elapsed 144.72s.
- `./test.sh` against the dockerized stack with `TEST_OTP_EMAIL` /
  `TEST_OTP_CODE` set: **11 passed, 0 skipped**.
- Manual smoke: `/otp/request` stores a `$2b$10$...` hash in Redis
  under `otp:<email_hash>`; `/otp/verify` with the correct code
  returns 200 + `Set-Cookie`; wrong code returns 400 with the
  envelope body `{"error": {"message": "invalid_or_expired_code", ...}}`.

## Repository hygiene check

`test_auth_test_otp_fixture.py::test_grep_hygiene_test_otp_only_in_three_locations`
walks `backend/app/` and asserts that exactly three source files
reference `test_otp_`:

- `app/settings.py` (the field definitions)
- `app/auth/router.py` (the request-handler branch)
- `app/auth/email/factory.py` (the startup guard)

A fourth touch-point anywhere would break CI -- the spec's
enumeration-resistance story depends on this being the exhaustive
list.
