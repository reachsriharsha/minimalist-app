# Changelog: feat_auth_001 — Auth foundation

## Added

- **Users, roles, identities schema.** Alembic migration
  `0002_create_auth.py` creates `users`, `roles`, `user_roles`,
  `auth_identities` and installs the `citext` Postgres extension.
  Seeds the two bootstrap roles `admin` and `user`.
- **SQLAlchemy 2.x models.** `User`, `Role`, `UserRole`,
  `AuthIdentity` under `backend/app/auth/models.py`. `User.roles` is a
  `secondary`-based relationship returning `list[Role]`.
- **Redis session store** under `backend/app/auth/sessions.py`:
  `create`, `get`, `delete`, `revoke_all_for_user`. Opaque 256-bit
  session IDs; pipelined writes; reverse-index set
  `user_sessions:<user_id>` for role-change revocation.
- **`SessionMiddleware`** in `backend/app/middleware.py`. One Redis
  `GET` per request; populates `request.state.auth`; clears the
  cookie on miss / malformed payload / malformed cookie. No DB hit.
- **Authorization dependencies** at
  `backend/app/auth/dependencies.py`: `current_user`,
  `require_authenticated`, `require_roles(*names)` (OR semantics,
  401 before 403).
- **ADMIN_EMAILS bootstrap** at `backend/app/auth/bootstrap.py`.
  Grants the `admin` role on first user creation when the email
  appears in the comma-separated env list. Idempotent.
- **`revoke_sessions_for_user(user_id)`** service helper in
  `backend/app/auth/service.py` for 002/003 to call on role changes.
- **`GET /api/v1/auth/me`** — authenticated; returns `{user_id,
  email, display_name, roles}`.
- **`POST /api/v1/auth/logout`** — authenticated; deletes the
  session in Redis, clears the cookie, returns `204 No Content`.
- **`POST /api/v1/_test/session`** — env-gated test-only mint
  endpoint, mounted only when `settings.env == "test"`. Removed by
  `feat_auth_002`.
- **Four new settings fields** in `backend/app/settings.py`:
  `session_cookie_name` (`"session"`), `session_ttl_seconds`
  (`86400`), `session_cookie_secure` (`False`), `admin_emails`
  (`""`). Computed `admin_emails_set` property returns a lower-cased
  `frozenset[str]`.
- **Four matching env vars** in `infra/.env.example` under a new
  `Auth (feat_auth_001)` heading.
- **Redis AOF durability tightened.** `infra/docker-compose.yml`
  Redis `command` now passes `--appendfsync everysec` alongside the
  existing `--appendonly yes`. Volume name `redisdata` preserved.

## Tests

- Seven new backend test modules under `backend/tests/` covering the
  session store, middleware, dependencies, ADMIN_EMAILS bootstrap,
  `/me` + `/logout` end-to-end, test-mint env gating, and the
  Alembic migration.
- One new external REST test (`tests/tests/test_auth.py`) verifying
  `/auth/me` and `/auth/logout` return 401 without a cookie on the
  dev compose stack.

## Changed

- `backend/app/main.py` installs `SessionMiddleware` between
  `RequestIDMiddleware` (outermost) and
  `ExceptionEnvelopeMiddleware`. Mounts the auth router under
  `/api/v1/auth` and the env-gated test router under `/api/v1/_test`
  when `env == "test"`.
- `backend/app/api/v1/__init__.py` now includes the auth router
  alongside the items router.
- `backend/alembic/env.py` imports `app.auth.models` as a
  side-effect import so autogenerate diffs see the new tables.
- `docs/tracking/features.md` and `docs/specs/README.md` advance
  `feat_auth_001` to `In Build` (and later `Merged` on PR merge).

## Out of scope (tracked for future features)

- Real OTP flow → `feat_auth_002`.
- Google OAuth flow → `feat_auth_003`.
- Frontend login UI → `feat_frontend_002`.
- Deployment docs (`docs/deployment/*`) → ride with 002/003.
