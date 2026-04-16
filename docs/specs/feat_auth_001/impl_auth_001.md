# Implementation Notes: feat_auth_001 — Auth foundation

## Summary

Implemented the auth foundation per the three spec files under
`docs/specs/feat_auth_001/`. Everything in the "In Scope" list of the
feature spec landed; everything in "Out of Scope" was skipped. Two
small deviations from the design spec are flagged at the bottom.

## What shipped

### Schema and ORM

- Alembic migration `backend/alembic/versions/0002_create_auth.py`
  creates `citext`, `users`, `roles`, `user_roles`, `auth_identities`
  and seeds the two role rows (`admin`, `user`). Constraint names
  follow the naming convention that `feat_backend_002` wired onto
  `Base.metadata`.
- SQLAlchemy models live at `backend/app/auth/models.py`. `User.roles`
  is a `secondary="user_roles"` relationship loaded with
  `lazy="selectin"` so eager reads are cheap when they happen, but we
  deliberately do not rely on that path on freshly-created async-session
  instances (see implementation note below).

### Session plumbing

- Redis-backed session store at `backend/app/auth/sessions.py`:
  `create`, `get`, `delete`, `revoke_all_for_user`. Opaque 256-bit IDs
  via `secrets.token_hex(32)`; JSON payloads; pipelined writes;
  reverse-index set `user_sessions:<user_id>` with the same TTL.
- `SessionMiddleware` lives in `backend/app/middleware.py` alongside the
  existing `RequestIDMiddleware` and `ExceptionEnvelopeMiddleware`. It
  parses the cookie, does one Redis `GET`, and populates
  `request.state.auth`. On miss / malformed payload / malformed cookie
  it logs `auth.session.expired_cookie_cleared` with a `session_id_hash`
  (never the raw ID) and appends a `Set-Cookie: <name>=; Max-Age=0`
  header. No DB hit.

### Middleware order

Installed as `RequestIDMiddleware → SessionMiddleware →
ExceptionEnvelopeMiddleware → app` (outermost first). This matches
§5.4 of the design doc: the request ID is bound before session work,
and any 401/403 raised by a dependency still flows through the
exception envelope.

### Authorization primitives

- `backend/app/auth/dependencies.py` exposes `current_user`,
  `require_authenticated` (alias), and `require_roles(*names)`. OR
  semantics across role names; unauthenticated always precedes
  unauthorized (401 > 403).
- `backend/app/auth/bootstrap.py` parses `ADMIN_EMAILS` and exposes
  `grant_admin_if_listed(user, session=..., settings=...)`. All
  association-table manipulation goes through explicit SELECT/INSERT.
- `backend/app/auth/service.py` exposes `revoke_sessions_for_user`
  (thin wrapper for stability across 002/003) and
  `find_or_create_user_for_test`, which is the ADMIN_EMAILS-aware
  helper the test-only mint endpoint uses.

### Endpoints

- `GET /api/v1/auth/me` and `POST /api/v1/auth/logout` are mounted
  under `/api/v1/auth`, always.
- `POST /api/v1/_test/session` is mounted only when
  `settings.env == "test"`. Verified both by unit tests that build the
  app with each env value and by the production dev compose stack
  (which runs with `ENV=dev` and correctly returns 404 on that route).

### Config

- Four new `Settings` fields: `session_cookie_name`,
  `session_ttl_seconds`, `session_cookie_secure`, `admin_emails`, plus
  an `admin_emails_set` property.
- Same four vars in `infra/.env.example` under a new `Auth
  (feat_auth_001)` heading.
- `infra/docker-compose.yml` Redis command extended from
  `--appendonly yes` to `--appendonly yes --appendfsync everysec`.
  Volume name `redisdata` preserved per the spec-level deviation
  documented in `design_auth_001.md`.

## Implementation notes

### Async-session + SQLAlchemy relationships

The original service-layer draft used `user.roles.append(role)` to
manipulate role membership, relying on `lazy="selectin"` to keep
reads cheap. In an async session that pattern raises
`sqlalchemy.exc.MissingGreenlet` whenever the relationship hasn't
been eagerly loaded yet (e.g., on a freshly inserted user):
attribute-access-triggered lazy loads are not bridged to `await`
automatically.

Fixed by routing every role write through explicit SELECT/INSERT on
the `user_roles` association table. The ORM relationship remains
loaded eagerly for read paths that *do* go through a full SELECT
(e.g., `/auth/me` does `db.get(User, ctx.user_id)` and could iterate
`user.roles` without issue) — but `service.py` and `bootstrap.py`
never touch that attribute on a freshly-created instance.

`find_or_create_user_for_test` therefore returns `(user,
sorted(role_names))` rather than just `user` so callers can build the
session payload from plain strings without re-reading the relationship.
This is a small shape change from the design spec, flagged below.

### Settings flow into handlers

Route handlers that need settings read them via a tiny `_settings`
dependency that pulls `request.app.state.settings` (installed by
`create_app` → `_make_lifespan`). Using the module-level
`get_settings` LRU cache instead would have broken tests that build
an app with a synthetic `Settings(env="test", admin_emails="...")`
instance, because the LRU cache only honors env vars.

### Email validation

The feature spec forbids new top-level dependencies. Pydantic's
`EmailStr` requires the `email-validator` package, which is not in
`pyproject.toml`. Replaced with a hand-rolled shape check (`@` must
be present, length ≥ 3) on the test-only mint request body. Real
provider-side validation lands with OTP (feat_auth_002) and Google
(feat_auth_003).

### No DB hit per request

`SessionMiddleware` makes one Redis `GET`; zero DB calls. The dev-loop
integration test `test_no_db_hit_on_missing_cookie` verifies this
against `/healthz` by wiring a SQLAlchemy `checkout` listener onto the
engine and confirming the counter stays at zero.

`GET /auth/me` does issue one DB query (`db.get(User, id)`) to fetch
`display_name`, which isn't stored in the session payload. That is by
design — keeping `display_name` out of the payload lets profile edits
propagate without needing session revocation. The "no DB hit per
request" invariant is specifically about the middleware and the
role-check fast path; both of those stay zero-DB.

## Deviations from the spec

1. **Service-layer return type.**
   `find_or_create_user_for_test` returns `(User, list[str])` rather
   than just `User`. The extra `role_names` list is the set of
   authoritative role names at commit time. Necessary to avoid a
   `MissingGreenlet` from the lazy-loaded `User.roles` relationship on
   a freshly-created instance (see note above). Callers (just
   `router.py` in this feature) simply unpack the pair.

2. **Email shape check instead of `EmailStr`.**
   Requirement 15 forbids new top-level dependencies, and pydantic's
   `EmailStr` pulls in `email-validator`. Schemas use `str` with a
   minimal `@`-present validator on `TestSessionRequest.email`. Real
   flows in 002/003 verify the email provider-side.

No other deviations. `citext` extension, cookie attributes, log event
shape, middleware order, env gating, tracker row, and REST suite
extension all match the spec verbatim.

## Test coverage

Seven new backend test modules:

- `test_auth_sessions.py` — 8 cases (Redis round-trip, TTL,
  malformed-payload tolerance, revoke-all, empty reverse index).
- `test_auth_middleware.py` — 7 cases (no-cookie, valid cookie,
  expired/malformed/malformed-length, RequestID-still-outermost,
  no-DB-on-healthz).
- `test_auth_dependencies.py` — 9 cases (401 vs 403 precedence, OR
  semantics).
- `test_auth_bootstrap.py` — 8 cases (empty / exact / case / whitespace
  / non-member / cache-reset / idempotent / helper).
- `test_auth_me_logout.py` — 10 cases (happy path, ADMIN_EMAILS
  bootstrap, non-bootstrap, extra roles, idempotent mint, revoke
  end-to-end, cookies absent/secure/insecure, logout-without-session
  without Redis DEL).
- `test_auth_test_mint_gating.py` — 4 cases across dev/test/prod.
- `test_migration_0002_auth.py` — 6 cases (upgrade/downgrade clean,
  citext uniqueness, cascade/restrict, constraint names).

External REST suite gains `tests/tests/test_auth.py` (2 cases: 401 on
`/auth/me` and `/auth/logout` without a cookie).

Full suite: 74 passed, 1 pre-existing skip (git-ignored-file check on
a bare repo), 0 failures. External suite: 9 passed.
