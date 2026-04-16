# Feature: Auth foundation — users, roles, identities, sessions

## Problem Statement

The backend today has no concept of "who is calling." `feat_backend_001` shipped a runnable FastAPI scaffold; `feat_backend_002` tightened its logging and layout discipline. Neither of them introduces a user, a role, or a session. Every subsequent feature — an admin-only endpoint, a per-user record, a rate-limited action — needs "who is this request?" to be a one-line dependency, not a design question.

The four-feature auth sequence is specified in full at `docs/design/auth-login-and-roles.md` (approved in brainstorming). This feature, `feat_auth_001`, is the **foundation**: the data model, the session plumbing, the authorization primitives, and the `GET /auth/me` + `POST /auth/logout` pair. It ships **no login paths of its own**. OTP login lands in `feat_auth_002`; Google OAuth lands in `feat_auth_003`; the UI lands in `feat_frontend_002`. This feature's sole job is to put the rails down so the next three features can be short.

Because real login flows do not land until `feat_auth_002`, this feature also ships a **temporary test-only endpoint** (`POST /api/v1/_test/session`) guarded to mount only when `settings.env == "test"`. It exists so the middleware, dependencies, and `/auth/me` + `/auth/logout` pair can be exercised end-to-end now, and is removed by `feat_auth_002` once OTP verify is the real session minter.

The full design rationale — session-vs-JWT trade-off, role model shape, identity auto-linking rule, security posture — is in §§1, 2, 3, 4, 6, 11, 14, 15 of the design doc. This spec does **not** restate that reasoning; it pulls only the parts that land in this feature.

## Requirements

### Functional

1. **Domain addition in `conventions.md` §1.** A new row `auth` — "Identity, authentication flows (OAuth + OTP), sessions, roles, authorization primitives." — is added to the approved-domains table. Folded in here per §14 of the design doc, not carved out as a separate `feat_conventions_NNN`. The human confirmed this folding during brainstorming.
2. **Design doc committed.** `docs/design/auth-login-and-roles.md` is currently untracked on `main`; it rides in on this spec PR so that all four auth planning cycles reference a committed file. No edits to its content — verbatim check-in.
3. **Postgres schema** — one new Alembic migration `backend/alembic/versions/0002_create_auth.py`. Creates the `citext` extension and the four tables `users`, `roles`, `user_roles`, `auth_identities` per §6.1 of the design doc. Seeds two rows into `roles` — `admin` and `user`. Uses the alembic naming convention that `feat_backend_002` wired onto `Base.metadata`.
4. **SQLAlchemy models** under `backend/app/auth/models.py` — `User`, `Role`, `UserRole`, `AuthIdentity`. Relationships match the schema. `User` exposes `.roles` as a collection loaded via the association table.
5. **Redis session store** — `backend/app/auth/sessions.py`. Exposes:
   - `create(user, *, redis) -> session_id` — pipelined `SET session:<id>` + `SADD user_sessions:<user_id>` + `EXPIRE user_sessions:<user_id>`, all with TTL `SESSION_TTL_SECONDS`.
   - `get(session_id, *, redis) -> AuthContext | None` — single `GET`, JSON-parsed.
   - `delete(session_id, user_id, *, redis) -> None` — `DEL session:<id>` + `SREM user_sessions:<user_id>`.
   - `revoke_all_for_user(user_id, *, redis) -> None` — §7.6 of the design doc.
   The `oauth_state:<state>` key is designed for single-use via `GETDEL` (per §6.2); the write side lands in `feat_auth_003`, but the helper's shape is fixed here.
6. **Session middleware** — `backend/app/middleware.py` gains a `SessionMiddleware` class. Installed in `app/main.py` between `RequestIDMiddleware` and the route. Reads the cookie, does one Redis `GET`, populates `request.state.auth: AuthContext | None`. **No DB hit per request.** On a valid cookie whose session has expired, clears the cookie.
7. **FastAPI dependencies** — `backend/app/auth/dependencies.py`:
   - `current_user(request) -> AuthContext` — raises 401 `not_authenticated` when `request.state.auth` is `None`.
   - `require_authenticated` — alias of `current_user` for readability at call sites that do not need the payload.
   - `require_roles(*names: str)` — factory that returns a dependency; OR semantics across names; raises 403 `forbidden` on miss.
8. **Endpoints (v1)**:
   - `GET /api/v1/auth/me` — authenticated; returns `{ "user_id", "email", "display_name", "roles" }`. Payload shape exactly matches §7.3 of the design doc.
   - `POST /api/v1/auth/logout` — authenticated; deletes the session in Redis, clears the cookie, returns `204 No Content`.
9. **Bootstrap hook** — `backend/app/auth/bootstrap.py`. Parses `ADMIN_EMAILS` once at startup (lower-cased set). Exposes `grant_admin_if_listed(user, db_session) -> bool`. The hook is wired into the user-creation path, but the user-creation path itself lives in 002 and 003. In this feature, the hook is exercised by the `_test/session` endpoint (which creates a user on first call) so `test_auth_001.md` can cover it.
10. **Service helper** — `revoke_sessions_for_user(user_id)` exported from `backend/app/auth/service.py`. Thin wrapper over `sessions.revoke_all_for_user`.
11. **Test-only session-mint endpoint** — `POST /api/v1/_test/session` mounts **only when `settings.env == "test"`**. Body: `{ "email": "...", "display_name": "...", "roles": ["admin"]? }`. Does find-or-create user, applies `ADMIN_EMAILS` bootstrap, optionally grants extra roles if passed, creates a session, sets the cookie, returns `200`. Removed by `feat_auth_002`.
12. **New environment variables** (added to `infra/.env.example` and to `app/settings.py`):
    - `SESSION_COOKIE_NAME=session`
    - `SESSION_TTL_SECONDS=86400`
    - `SESSION_COOKIE_SECURE=false`
    - `ADMIN_EMAILS=` (empty; comma-separated list, case-insensitive)
13. **Redis durability** — `infra/docker-compose.yml` `redis.command` extended from `--appendonly yes` to `--appendonly yes --appendfsync everysec`. No volume rename. (§12 of the design doc uses `redis-data`; we preserve the existing `redisdata` name — see "Deviations from the design doc" in `design_auth_001.md`.)
14. **Tracking** — `docs/tracking/features.md` gets a new row for `feat_auth_001`. `docs/specs/README.md` feature roster gains a row for `feat_auth_001`.

### Non-functional

15. **No new top-level dependencies.** Session JSON uses stdlib `json`. Session IDs use stdlib `secrets`. `citext` is a Postgres extension, not a Python dependency.
16. **No DB hit per request.** Role checks read from the session payload — `AuthContext.roles` — exactly as §2 of the design doc promises.
17. **No frontend changes.** The login UI is `feat_frontend_002`.
18. **No OTP code, no Google OAuth code, no `EmailSender` abstraction.** Those belong to 002 and 003.
19. **No deployment docs** (`docs/deployment/*`). Those land with the features that introduce the external dependencies.
20. **No linting, formatting, or pre-commit tooling** (per `conventions.md` §11).
21. **Backward-compatible with existing routes.** `GET /api/v1/hello`, `/healthz`, `/readyz` are untouched. No existing middleware ordering changes except the insertion of `SessionMiddleware` per §5.4 of the design doc.

## User Stories

- As **Vulcan** (builder of `feat_auth_002` and `feat_auth_003`), I want the `users` / `roles` / `auth_identities` tables, the Redis session helpers, the bootstrap hook, and the `current_user` dependency to already exist, so the OTP and OAuth features can focus on their provider-specific code and not reinvent session plumbing.
- As a **human operator bringing this repo up locally**, I want `make up && make test` to keep passing after this feature lands, with the new auth tables migrated and the session cookie round-trip verified by the test-only mint endpoint. I do not want to have to configure Google or Resend to see green tests.
- As a **reader of the four-feature auth sequence**, I want one committed design doc (`docs/design/auth-login-and-roles.md`) that all four features' specs reference, so the architectural decisions live in one place and the per-feature specs stay focused on their slice.
- As a **security-minded reviewer**, I want role data to ride in the session payload (no per-request DB hit), role-change revocation to be a single helper call, and `ADMIN_EMAILS` to be documented as bootstrap-only (not a live sync) so the privilege model is legible without reading the code.

## Scope

### In Scope

- `docs/design/auth-login-and-roles.md` — verbatim commit of the already-written brainstorming artifact.
- `conventions.md` §1 — one-row addition for the `auth` domain.
- `backend/alembic/versions/0002_create_auth.py` — single migration: `citext`, four tables, role seeds.
- `backend/app/auth/__init__.py`, `models.py`, `schemas.py`, `sessions.py`, `dependencies.py`, `bootstrap.py`, `service.py`, `router.py`.
- `backend/app/middleware.py` — `SessionMiddleware` class added; existing classes untouched.
- `backend/app/main.py` — install `SessionMiddleware`; mount auth router at `/api/v1/auth`; mount the test-only router at `/api/v1/_test` when `env == "test"`.
- `backend/app/api/v1/__init__.py` — include the new `auth` router.
- `backend/app/settings.py` — four new fields (§11 of the design doc).
- `infra/.env.example` — four new variables with defaults.
- `infra/docker-compose.yml` — redis `command` adds `--appendfsync everysec`.
- `backend/tests/` — new tests per `test_auth_001.md`.
- `docs/specs/feat_auth_001/{feat,design,test}_auth_001.md` — the three spec files themselves.
- `docs/specs/README.md`, `docs/tracking/features.md` — tracking rows.

### Out of Scope

- `POST /auth/otp/request`, `POST /auth/otp/verify`, `EmailSender`, `ConsoleEmailSender`, `ResendEmailSender`, `backend/app/auth/otp.py`, `backend/app/auth/email/` — all belong to `feat_auth_002`.
- `GET /auth/google/start`, `GET /auth/google/callback`, Google JWKS verification, PKCE helpers, `backend/app/auth/google.py` — all belong to `feat_auth_003`.
- Any frontend work: login page, `AuthContext`, protected-route wrapper — `feat_frontend_002`.
- `docs/deployment/google-oauth-setup.md` (→ 003), `docs/deployment/email-otp-setup.md` (→ 002), `docs/deployment/README.md` (→ whichever of 002/003 ships first).
- User profile editing, account-linking UI, admin dashboard, second OAuth provider, MFA, password reset, account self-deletion (non-goals per §15 of the design doc).
- Live sync of `ADMIN_EMAILS` — documented explicitly as bootstrap-only.
- Per-request DB hit / stale-role correction beyond `revoke_sessions_for_user`.

## Acceptance Criteria

- [ ] `conventions.md` §1 domains table contains a row `auth | Identity, authentication flows (OAuth + OTP), sessions, roles, authorization primitives.`
- [ ] `docs/design/auth-login-and-roles.md` is committed under this PR with content byte-identical to the existing untracked working-tree file.
- [ ] `backend/alembic/versions/0002_create_auth.py` creates the four tables with columns, types, nullability, FKs, cascade behavior, and the `(provider, provider_user_id)` unique constraint exactly as §6.1 specifies. The migration installs the `citext` extension and seeds two role rows (`admin`, `user`).
- [ ] `alembic upgrade head` against a clean Postgres creates the schema; `alembic downgrade base` removes the four tables and the extension cleanly.
- [ ] `backend/app/auth/models.py` exposes `User`, `Role`, `UserRole`, `AuthIdentity`; `User.roles` is a SQLAlchemy relationship returning `list[Role]`.
- [ ] `backend/app/auth/sessions.py` exposes `create`, `get`, `delete`, `revoke_all_for_user` with the contract in requirement 5.
- [ ] `SessionMiddleware` populates `request.state.auth` without any DB call. A log of the DB query log during a `GET /api/v1/auth/me` call shows zero queries.
- [ ] `GET /api/v1/auth/me` with a valid session cookie returns HTTP 200 and the payload shape of §7.3.
- [ ] `GET /api/v1/auth/me` without a cookie returns HTTP 401 with body `{"detail": "not_authenticated"}`.
- [ ] `POST /api/v1/auth/logout` with a valid session cookie returns HTTP 204, `DEL`s the session key in Redis, removes the session ID from the `user_sessions:<uid>` set, and sets `Set-Cookie: <name>=; Max-Age=0`.
- [ ] `require_roles("admin")` on a session whose payload does not contain `"admin"` in `roles` returns HTTP 403 `{"detail": "forbidden"}` without touching the DB.
- [ ] `require_roles("admin", "user")` passes when **either** role is present (OR semantics).
- [ ] `ADMIN_EMAILS=alice@x.com` and a first-time mint for `alice@x.com` grants both `user` and `admin` roles. With `ADMIN_EMAILS=""` (empty), only `user` is granted.
- [ ] `revoke_sessions_for_user(42)` wipes every `session:<id>` key whose ID was present in `user_sessions:42`, then wipes `user_sessions:42` itself. A subsequent `GET /api/v1/auth/me` with a previously-valid cookie returns 401.
- [ ] `POST /api/v1/_test/session` is **not** registered when `env == "dev"` (HTTP 404). It **is** registered when `env == "test"`.
- [ ] `infra/.env.example` contains the four new lines under an `# ---- Auth (feat_auth_001) ----` heading with the defaults specified in requirement 12.
- [ ] `infra/docker-compose.yml` `redis.command` is `redis-server --appendonly yes --appendfsync everysec`. `redisdata` volume name is unchanged.
- [ ] `docs/tracking/features.md` contains a row for `feat_auth_001` whose status advances `Planned → In Spec` (this PR) → `Ready` (on merge). `docs/specs/README.md` roster table contains the same row.
- [ ] `uv run pytest` from `backend/` with `ENV=test` passes, including every new test file named in `test_auth_001.md`.
- [ ] `test.sh` continues to pass.
