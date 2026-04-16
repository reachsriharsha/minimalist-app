# Design: Auth foundation — users, roles, identities, sessions

## Source of truth

The architectural decisions — why server-side sessions over JWT, why opaque cookie, why role data in the session payload, why `citext` on email, why auto-link on verified email, why `ADMIN_EMAILS` is not a live sync — live in **`docs/design/auth-login-and-roles.md`**. This design spec does **not** repeat that reasoning. It describes the concrete file-level work that lands in `feat_auth_001` and references:

- **§5** — module layout, endpoint inventory, middleware order.
- **§6** — Postgres schema and Redis keyspaces (001 lands only the `session:*` and `user_sessions:*` keys; the `otp:*` and `oauth_state:*` keys are defined but written by 002/003).
- **§7** — data-flow narratives (this feature covers §7.3 `/auth/me`, §7.4 session creation, §7.5 logout, §7.6 revocation, §7.7 `ADMIN_EMAILS`). §§7.1 and 7.2 are out of scope.
- **§12** — Redis persistence in compose.

When this spec says "per §6.1" it means "see the design doc, section 6.1 — don't duplicate."

## Approach

Five disjoint pieces of work, one build:

1. **Check in the design doc.** Move `docs/design/auth-login-and-roles.md` from untracked into the tree verbatim. All four auth features reference it.
2. **Schema.** One Alembic migration `0002_create_auth.py` creating `citext`, `users`, `roles`, `user_roles`, `auth_identities`, seeding two role rows. SQLAlchemy models under `app/auth/models.py`.
3. **Session plumbing.** `app/auth/sessions.py` (Redis store), `SessionMiddleware` in `app/middleware.py`, `AuthContext` dataclass.
4. **Authorization primitives.** `app/auth/dependencies.py` with `current_user`, `require_authenticated`, `require_roles(*names)`. `app/auth/bootstrap.py` for `ADMIN_EMAILS`. `app/auth/service.py` for `revoke_sessions_for_user`.
5. **Endpoints + test-only mint.** `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`, and `POST /api/v1/_test/session` (env-gated). Config additions and the compose redis durability tweak round it out.

Nothing in this feature calls Google, reads email, or sends a message. The only external surface is the `/auth/me` + `/auth/logout` pair plus the env-gated mint. That is deliberate: it lets the session plumbing be fully tested before the real login paths land.

## Files to Create

| Path | Purpose |
|---|---|
| `docs/design/auth-login-and-roles.md` | Move from untracked into the tree. Byte-identical to the existing working-tree file. |
| `backend/alembic/versions/0002_create_auth.py` | Migration: `citext` + four tables + role seeds. |
| `backend/app/auth/__init__.py` | Package marker; re-exports `router`. |
| `backend/app/auth/models.py` | `User`, `Role`, `UserRole`, `AuthIdentity` SQLAlchemy 2.x models. |
| `backend/app/auth/schemas.py` | `MeResponse`, `AuthContext` (pydantic/dataclass), `TestSessionRequest`. |
| `backend/app/auth/sessions.py` | Redis session store: `create`, `get`, `delete`, `revoke_all_for_user`. |
| `backend/app/auth/dependencies.py` | `current_user`, `require_authenticated`, `require_roles`. |
| `backend/app/auth/bootstrap.py` | `ADMIN_EMAILS` parsing, `grant_admin_if_listed`. |
| `backend/app/auth/service.py` | `revoke_sessions_for_user`, thin find-or-create helpers used by the test-only mint. |
| `backend/app/auth/router.py` | `GET /me`, `POST /logout`, plus the env-gated `/_test/session` mounted on a separate router. |
| `backend/tests/test_auth_sessions.py` | Unit tests for the Redis session store. |
| `backend/tests/test_auth_middleware.py` | Integration tests for `SessionMiddleware` behavior. |
| `backend/tests/test_auth_dependencies.py` | Unit tests for `current_user`, `require_roles`. |
| `backend/tests/test_auth_bootstrap.py` | Unit tests for `ADMIN_EMAILS` grant-on-first-login. |
| `backend/tests/test_auth_me_logout.py` | End-to-end tests for `/me` + `/logout` using the test-only mint. |
| `backend/tests/test_auth_test_mint_gating.py` | Verifies `_test/session` is 404 when `env != "test"`. |
| `docs/specs/feat_auth_001/feat_auth_001.md` | Feature spec. |
| `docs/specs/feat_auth_001/design_auth_001.md` | This file. |
| `docs/specs/feat_auth_001/test_auth_001.md` | Test spec. |

## Files to Modify

| Path | Change |
|---|---|
| `conventions.md` | §1 domains table — add `auth` row (verbatim text in requirement 1 of the feature spec). |
| `backend/app/middleware.py` | Add `SessionMiddleware` class. No change to existing middleware. |
| `backend/app/main.py` | Install `SessionMiddleware` per §5.4 of the design doc. Mount auth router at `/api/v1/auth`. When `settings.env == "test"`, additionally mount the test-only router at `/api/v1/_test`. |
| `backend/app/api/v1/__init__.py` | `include_router(auth_router, prefix="/auth", tags=["auth"])` alongside the existing items router. |
| `backend/app/settings.py` | Add four new fields: `session_cookie_name`, `session_ttl_seconds`, `session_cookie_secure`, `admin_emails` (raw string). Plus a computed property `admin_emails_set` returning `frozenset[str]` of lower-cased addresses. |
| `infra/.env.example` | Add the four new lines under an `# ---- Auth (feat_auth_001) ----` heading, as laid out in §11 of the design doc. |
| `infra/docker-compose.yml` | `redis.command` becomes `["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]`. `redisdata` volume is preserved. |
| `docs/specs/README.md` | Roster table gains a row for `feat_auth_001`. |
| `docs/tracking/features.md` | One new row; `Status=Specced` with Spec PR and Issues backfilled. |

## Files to Delete

None. This feature only adds.

## Middleware order (per §5.4 of the design doc)

```
RequestIDMiddleware          (existing; outermost)
ExceptionEnvelopeMiddleware  (existing)
SessionMiddleware            (NEW — inserted between the above and the route)
FastAPI routing
```

`app.add_middleware` prepends to the stack (LIFO). Current order in `main.py` adds `ExceptionEnvelopeMiddleware` first, then `RequestIDMiddleware`. To land `SessionMiddleware` strictly between `RequestIDMiddleware` and route dispatch, add it **between** the two existing `add_middleware` calls, in this order:

```python
app.add_middleware(ExceptionEnvelopeMiddleware)       # innermost
app.add_middleware(SessionMiddleware)                 # NEW
app.add_middleware(RequestIDMiddleware, header_name=...)  # outermost
```

This keeps `RequestIDMiddleware` outermost (so request IDs are bound before session work, matching the bind-ordering invariant `feat_backend_002` established) and runs `SessionMiddleware` before the exception envelope wraps errors. Any 401 raised by a route dependency still flows through the envelope normally.

## Data flow

### Request lifecycle with a valid cookie

```
client  (Cookie: session=abc123...)
  → RequestIDMiddleware        (binds request_id into structlog contextvars)
  → SessionMiddleware          (NEW)
      ├── read settings.session_cookie_name from request.cookies
      ├── GET session:abc123... (one Redis hop; sub-ms; NO DB)
      ├── parse JSON → AuthContext(user_id, email, roles, session_id)
      └── request.state.auth = ctx
  → ExceptionEnvelopeMiddleware
  → FastAPI dispatch
  → current_user dep: returns request.state.auth or raises HTTPException(401)
  → route handler
```

### No cookie, expired session, malformed payload

All three collapse to the same outcome: `request.state.auth = None`. If the cookie was present but the Redis key was missing or malformed, the middleware **also** appends a `Set-Cookie: <name>=; Max-Age=0` to the response so the browser stops sending it. Log event: `auth.session.expired_cookie_cleared` (reason field distinguishes `missing_key`, `malformed_payload`, `malformed_cookie`).

### Session creation (shared helper, used by the test-only mint here and by OTP/OAuth in 002/003)

```python
session_id = secrets.token_hex(32)                          # 64 hex chars
payload = {
    "user_id": user.id,
    "email": user.email,
    "roles": [r.name for r in user.roles],
    "created_at": now_iso(),
}
pipe = redis.pipeline()
pipe.set(f"session:{session_id}", json.dumps(payload), ex=settings.session_ttl_seconds)
pipe.sadd(f"user_sessions:{user.id}", session_id)
pipe.expire(f"user_sessions:{user.id}", settings.session_ttl_seconds)
await pipe.execute()

response.set_cookie(
    settings.session_cookie_name,
    session_id,
    max_age=settings.session_ttl_seconds,
    httponly=True,
    secure=settings.session_cookie_secure,
    samesite="lax",
    path="/",
)
```

### Logout

```
POST /api/v1/auth/logout  (Cookie: session=abc123...)
  → SessionMiddleware populates request.state.auth
  → route sees ctx.session_id = "abc123..."
  → sessions.delete("abc123...", ctx.user_id, redis=...)
      ├── DEL session:abc123...
      └── SREM user_sessions:<uid> abc123...
  → response.delete_cookie(name, path="/")
  → 204 No Content
```

### Role-change revocation

```python
# backend/app/auth/service.py
async def revoke_sessions_for_user(user_id: int, *, redis) -> None:
    session_ids = await redis.smembers(f"user_sessions:{user_id}")
    if session_ids:
        keys = [f"session:{sid.decode() if isinstance(sid, bytes) else sid}" for sid in session_ids]
        await redis.delete(*keys)
    await redis.delete(f"user_sessions:{user_id}")
```

`DEL`-based, not update-based — predictable, no races. Not wired to a user-facing endpoint in 001; it exists so 002 and 003 can call it without introducing new infra.

## Postgres schema — per §6.1 of the design doc

The SQL shape is specified in the design doc; the migration file is a faithful translation. Key properties (re-stated only as acceptance hooks for `test_auth_001.md`, not as design):

- `email` is `CITEXT NOT NULL UNIQUE` on `users`; `citext` extension created in the same migration, **before** the `users` table.
- `roles.name` is `VARCHAR(64) NOT NULL UNIQUE`. Seeds `('admin')`, `('user')` inline in the migration.
- `user_roles` composite PK `(user_id, role_id)`. FK `user_id → users(id)` is `ON DELETE CASCADE`; FK `role_id → roles(id)` is `ON DELETE RESTRICT`.
- `auth_identities.provider` is `VARCHAR(32)`; `provider_user_id` is `VARCHAR(255)`; unique index on `(provider, provider_user_id)`. Regular index on `user_id`. `email_at_identity` is `CITEXT NOT NULL`.
- All timestamp columns are `TIMESTAMPTZ`.
- Alembic naming convention (wired in `feat_backend_002`) produces deterministic constraint names: `pk_users`, `uq_roles_name`, `fk_auth_identities_user_id_users`, `uq_auth_identities_provider`, etc.

The `downgrade()` drops in reverse order — `auth_identities`, `user_roles`, `roles`, `users` — and `DROP EXTENSION citext`.

## Redis keyspaces used by this feature

Per §6.2 of the design doc. Only two are written here; the other two are reserved for 002 and 003.

| Key | TTL | Written by | In this feature? |
|---|---|---|---|
| `session:<64-hex>` | `SESSION_TTL_SECONDS` | session creation | YES — test-mint endpoint + OTP/OAuth later |
| `user_sessions:<user_id>` | matches above | session creation | YES |
| `otp:<email_hash>` | 600 | OTP request | NO — 002 |
| `otp_rate:<email_hash>:*` | 60 / 3600 | OTP request | NO — 002 |
| `oauth_state:<state>` | 600 | `/google/start` | NO — 003 |

## `AuthContext` shape

```python
# backend/app/auth/schemas.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: int
    email: str
    roles: tuple[str, ...]
    session_id: str
```

Frozen + slotted → cheap, hashable, explicitly immutable. Roles is a tuple (not a list) so the context can be cached safely across handlers if anyone ever wants to; for now it only lives on `request.state`.

## Test-only session-mint endpoint

The endpoint's job is to let `test_auth_001.md` exercise the middleware, the `/auth/me` + `/auth/logout` pair, `require_roles`, and `ADMIN_EMAILS` bootstrap before OTP verify (`feat_auth_002`) becomes the real path.

Shape:

```python
# backend/app/auth/router.py — guarded registration
if settings.env == "test":
    test_router = APIRouter(prefix="/_test", tags=["_test"])

    @test_router.post("/session", status_code=200)
    async def mint_test_session(
        body: TestSessionRequest,
        response: Response,
        session: AsyncSession = Depends(get_session),
        redis: Redis = Depends(get_redis),
    ) -> MeResponse:
        user = await service.find_or_create_user_for_test(
            session, email=body.email, display_name=body.display_name,
            extra_roles=body.roles or [],
        )
        session_id = await sessions.create(user, redis=redis)
        response.set_cookie(...)   # same helper as the real flows will use
        return MeResponse(user_id=user.id, email=user.email,
                          display_name=user.display_name,
                          roles=[r.name for r in user.roles])
```

Gating happens in `app/main.py`:

```python
if resolved.env == "test":
    from app.auth.router import test_router
    app.include_router(test_router, prefix="/api/v1")
```

Three consequences:
- In `dev` and `prod` builds the symbol is imported only when `env == "test"`, so production images never register the route.
- When Vulcan ships `feat_auth_002`, the file-level delete is three lines plus one import removal.
- The `env_gating` test in `test_auth_test_mint_gating.py` hits the endpoint under both `env=dev` and `env=test` by rebuilding the app via `create_app(Settings(env=...))`.

## Settings additions

```python
# backend/app/settings.py (additions)

class Settings(BaseSettings):
    # ... existing fields ...

    # Auth (feat_auth_001)
    session_cookie_name: str = "session"
    session_ttl_seconds: int = 86400
    session_cookie_secure: bool = False
    admin_emails: str = ""   # raw comma-separated; parse via property

    @property
    def admin_emails_set(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower()
            for e in self.admin_emails.split(",")
            if e.strip()
        )
```

Raw string field + computed `frozenset` property mirrors how pydantic-settings prefers env-fed comma-lists (no custom validator, no JSON parsing surprise). Empty `ADMIN_EMAILS` → empty set → `grant_admin_if_listed` always returns `False`.

## `infra/.env.example` addition

Append, preserving the existing file's tone and section headings:

```ini
# ---- Auth (feat_auth_001) -----------------------------------------------
# Session cookie and role-bootstrap controls for the auth foundation.
SESSION_COOKIE_NAME=session
SESSION_TTL_SECONDS=86400
SESSION_COOKIE_SECURE=false        # flip to true in staging/prod
ADMIN_EMAILS=                      # comma-separated; empty = no bootstrap admin
```

The 002 and 003 env blocks from §11 of the design doc are **not** added here. They land with their own features.

## Deviations from the design doc

The design doc is authoritative. The deviations below are small enough to surface in the spec rather than re-opening the doc.

1. **Redis volume name.** §12 of the design doc names `redis-data` as the volume; the existing `infra/docker-compose.yml` already declares `redisdata` (no hyphen) as a top-level volume and it is populated on existing developer machines. Renaming would require a manual `docker volume rm`. We keep `redisdata`. The durability change (`--appendfsync everysec` added to the existing `--appendonly yes`) stands. If the human prefers the design-doc name, we rename in this PR and flag the disposable-local-data consequence.
2. **`models.py` file scope.** §5.1 of the design doc lists a flat `app/auth/{models.py, schemas.py, ...}`. That matches the package layout we are shipping. No deviation — called out only because `feat_backend_002` uses per-domain folders for business resources (`app/items/`); `app/auth/` is the second such folder, consistent with the rule, not exception to it.

## Edge cases and risks

- **`citext` extension permissions.** `CREATE EXTENSION citext` needs superuser (or a role with the `CREATE` privilege on the database). The dev-compose Postgres user is `postgres` (superuser) so local `alembic upgrade head` works. Production deploys are the operator's problem, documented later. Migration uses `CREATE EXTENSION IF NOT EXISTS citext` to stay idempotent.
- **Stale roles in an active session.** Covered by `revoke_sessions_for_user` — by design. The session payload is a cache; the rule is "revoke, not update." See §7.6 of the design doc.
- **Cookie-clear on malformed payload.** A corrupted Redis value (human-edit, partial write, Redis bug) must not hang the request. `SessionMiddleware` catches the JSON-decode error, logs `auth.session.expired_cookie_cleared reason=malformed_payload`, clears the cookie, sets `request.state.auth = None`, and continues.
- **Cookie signed vs unsigned.** Opaque session IDs are unguessable (256 bits from `secrets.token_hex(32)`). No HMAC on the cookie value — unnecessary when the cookie value is a random ID and the lookup-side is the check. Per §2 of the design doc.
- **`SameSite` and local dev.** `samesite="lax"` with `secure=False` works on `http://localhost`. Browsers do not require Secure on localhost. Staging/prod override: `SESSION_COOKIE_SECURE=true` + HTTPS.
- **Test-only mint left in a non-test build.** Guarded both at import time (`if env == "test"`) and at mount time (`if env == "test"`). A deployment that accidentally shipped `ENV=test` would expose the route — but that same deployment would also have wrong log levels and test-mode behavior throughout. Not a unique risk of the mint endpoint. `feat_auth_002` removes it entirely anyway.
- **Session-list-size unboundedness.** `user_sessions:<uid>` is a Redis `SET`. A pathological user who logs in from many devices accumulates entries. With a 1-day TTL on every session and the reverse-index key, the set bounds itself at "however many logins in the last 24h" — realistic bound. No cleanup job needed.
- **Pre-existing `RequestIDMiddleware` and structlog contextvars.** `SessionMiddleware` binds nothing into contextvars in this feature (no `session_id` in every log line), because doing so would leak session IDs (raw) or require a hashing hook. Logs that want the session principal emit `session_id_hash=...` explicitly per §10 of the design doc. 001 does not introduce new log events beyond the expired-cookie-clear one; 002 and 003 introduce the rest.
- **`/auth/logout` with no session.** If the middleware produced `request.state.auth = None`, `current_user` raises 401 before the handler runs. Callers who want "clear client state even if server state is gone" use `response.delete_cookie` client-side. No change to server semantics.
- **Pytest async-session fixture.** Existing `conftest.py` already provides an `AsyncClient` against `create_app`. New tests add a fixture that overrides `Settings(env="test")` and tears down the session store between tests (`FLUSHDB` on a test-only Redis DB index, same pattern as the existing tests).
- **Alembic downgrade leaves `CITEXT` installed if shared.** The migration's `downgrade()` drops the extension; if another migration in the future also needs `citext`, that migration must re-create it (or declare a no-op for already-installed case via `IF NOT EXISTS`). Documented inline in the migration file.

## Security considerations

Full posture table lives at §8 of the design doc. For this feature specifically:

- **Session ID entropy:** `secrets.token_hex(32)` → 256 bits. Brute force infeasible.
- **Cookie flags:** `HttpOnly=True`, `SameSite=Lax`, `Secure` controlled by env. XSS cannot read the cookie; CSRF on `/auth/logout` is blunted by `SameSite=Lax` (lax lets top-level GETs ride but blocks cross-site POSTs).
- **No per-request DB read** means a compromised Redis could silently issue tokens; the mitigation is operator-side Redis isolation (no public exposure, TLS in prod). `infra/docker-compose.yml` leaves Redis on the internal `appnet` only — no host port publish.
- **Test-only mint endpoint:** `env == "test"` guard. Can be invoked only in the test container. If someone exports `ENV=test` in a production shell, that is the same footgun as setting `LOG_LEVEL=DEBUG`. Rely on env-var hygiene; do not add a second guard.
- **`ADMIN_EMAILS` bootstrap**: lives in the env, not in the repo. Granted once on user creation. Demotion requires both env edit **and** a DB write. Documented in the deployment guide when `feat_auth_003` ships.
- **Session hashing in logs:** the one log event this feature emits (`auth.session.expired_cookie_cleared`) uses `session_id_hash=sha256(id)[:16]` per §10. Never logs the raw cookie value.

## Open questions

None blocking. Decisions already closed in brainstorming and re-anchored by this spec:

- Atlas-only PR for this feature; Vulcan in a later session.
- Test-only mint endpoint lives in 001, removed in 002 — human approved during brainstorming.
- Deployment docs deferred to the feature that introduces the external dependency — confirmed.
- `conventions.md` §1 edit folds into this PR rather than a dedicated `feat_conventions_NNN` — human approved during brainstorming.
- `redisdata` volume name preserved (spec-local deviation from the design doc; see "Deviations" above).
