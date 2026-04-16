# Design: Auth — Google OAuth + Email OTP Login with Roles

- **Status:** Approved (brainstorming complete — implementation plans not yet written)
- **Date:** 2026-04-16
- **Scope:** Adds password-less authentication (Google OAuth + email OTP), a user/role/identity data model, Redis-backed sessions, and the two external-service deployment guides.
- **Introduces new domain:** `auth` (per `conventions.md` §1 — approved during brainstorming).
- **Delivers as four features:** `feat_auth_001`, `feat_auth_002`, `feat_auth_003`, `feat_frontend_002`.

This spec captures the agreed design. Each of the four features will get its own `feat_*.md`, `design_*.md`, and `test_*.md` trio under `docs/specs/` when Atlas plans them; those will consume this design as their source of truth.

---

## 1. Feature roster

New domain to add to `conventions.md` §1:

| Domain | Scope |
|---|---|
| `auth` | Identity, authentication flows (OAuth + OTP), sessions, roles, authorization primitives. |

Four features, strict ordering — each merges before the next starts:

| Feature ID | Scope | What merges in |
|---|---|---|
| `feat_auth_001` | **Foundation.** Users + roles + identities schema, Alembic migration, session middleware (Redis-backed httpOnly cookie, 1-day absolute TTL, AOF on), `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`, role-gate FastAPI dependency, seeded `admin`+`user` roles, `ADMIN_EMAILS` bootstrap hook. Conventions edit folded in. | Schema + session plumbing. Exercised by a temporary test-only "mint a session" endpoint enabled only when `env=test`. |
| `feat_auth_002` | **Email OTP.** `EmailSender` abstraction, `ConsoleEmailSender` + `ResendEmailSender`, `POST /auth/otp/request`, `POST /auth/otp/verify`, Redis-backed rate limiting + OTP storage (hashed), `docs/deployment/email-otp-setup.md`. | First real login path. Removes the temp test-mint endpoint from 001. |
| `feat_auth_003` | **Google OAuth.** `GET /auth/google/start`, `GET /auth/google/callback`, state + PKCE in Redis, ID-token verification via Google JWKS, auto-link on verified email, `docs/deployment/google-oauth-setup.md`. | Second login path. |
| `feat_frontend_002` | **Login UI.** Login page with "Sign in with Google" button + OTP request/verify form, `AuthContext`, protected-route wrapper, "signed in as Alice (admin)" header, logout button. | User-facing flow. |

The `auth` domain addition and the two new `conventions.md` rows land **inside `feat_auth_001`** rather than as a separate conventions PR.

---

## 2. Session & token model (the foundational choice)

**Decision: server-side sessions in Redis, opaque session ID in an httpOnly cookie.** Not JWT.

**Why:**
- Already run Redis — no new infra.
- Revocation is instant (`DEL session:<id>` on logout or role change).
- httpOnly cookie defends against XSS; `SameSite=Lax` defends against CSRF. Browser apps are usually more exposed to XSS than CSRF, so this is the stronger default than JWT-in-localStorage.
- No signing-key management.
- Per-request check is a single Redis GET (sub-millisecond, in-memory) — **no Postgres hit per request**. Role data lives in the session payload.

**Session TTL:** 1 day **absolute** (not sliding). Set once at login, same value on both the Redis key (`EX 86400`) and the cookie (`Max-Age=86400`).

**Redis durability:** `appendonly yes`, `appendfsync everysec` — routine restart loses at most ~1 second of session writes. A wiped Redis just logs everyone out; users click a login link and get a fresh session. No data loss (users/roles/identities live in Postgres).

**No-DB-per-request property:** the session payload in Redis includes `user_id`, `email`, `roles[]`. `SessionMiddleware` reads the cookie, does one Redis GET, attaches `AuthContext` to `request.state`. Route handlers read from there — no DB call. Stale-role correction is handled by `revoke_sessions_for_user()` on role change.

---

## 3. Role model

**Decision: many-to-many `users` ↔ `roles` via `user_roles`.**

**Seeded roles:** `admin`, `user` (only two, intentionally minimal for a template).

**New-user default:** every new user auto-gets the `user` role. If their email (case-insensitive) is in `ADMIN_EMAILS` they additionally get `admin` on first login. `ADMIN_EMAILS` is **not** a live sync — demoting an admin requires both removing from the env var *and* `DELETE FROM user_roles WHERE user_id=X AND role_id=<admin>`.

**Authorization primitive:** FastAPI dependency `require_roles("admin")` (accepts multiple; OR semantics). Raises 403 on missing role. No per-request DB hit — reads from the session payload.

Future role-permission expansion (RBAC) can layer on top by adding a `permissions` table and extending the dependency. Not in scope.

---

## 4. Identity model

**Decision: `users` + `auth_identities` (one user, N identities).**

A user has one canonical row in `users`. Each login method — Google, email OTP — is an independent row in `auth_identities`. Two identities for the same user represent two independent proofs of that identity (Google's vouching + our OTP's mailbox-control proof). Removing one doesn't affect the other.

**Auto-linking rule:** when a Google login's verified email (`email_verified=true`) matches an existing `users.email`, the new Google identity is attached to that existing user automatically. Without auto-linking, users would end up with duplicate accounts if they switched methods. Auto-linking on **unverified** Google emails is **refused** (attacker could register an unverified Google account with your email and hijack).

### 4.1 Worked example — same email, both methods

**Day 1: Alice signs in with Google.**

Google returns `sub=111222333`, `email=alice@x.com`, `email_verified=true`, `name="Alice Smith"`.

Lookup identity `(google, 111222333)` → none. Lookup `users.email=alice@x.com` → none. Create:

```
users
 id | email       | display_name
 42 | alice@x.com | Alice Smith

auth_identities
 id | user_id | provider | provider_user_id | email_at_identity
  1 |    42   | google   | 111222333        | alice@x.com
```

**Day 2: Alice requests an OTP for `alice@x.com` and verifies it.**

Lookup identity `(email, alice@x.com)` → none. Lookup `users.email=alice@x.com` → user 42 found. OTP proved mailbox control, so auto-link:

```
auth_identities (after day 2)
 id | user_id | provider | provider_user_id | email_at_identity
  1 |    42   | google   | 111222333        | alice@x.com  ← day 1, untouched
  2 |    42   | email    | alice@x.com      | alice@x.com  ← day 2, new row
```

`users` still has one row. The email appears in three places:
- `users.email` (canonical, current)
- `auth_identities[1].email_at_identity` (what Google said)
- `auth_identities[2].email_at_identity` (what OTP verified)

### 4.2 Worked example — different emails per method (edge case)

Alice's Google account is `alice@gmail.com`; her work mailbox is `alice@company.com`.

**Day 1 Google** → `users(42, alice@gmail.com)` + `auth_identities(1, 42, google, sub, alice@gmail.com)`.

**Day 2 OTP for alice@company.com** → identity lookup miss, user lookup by `alice@company.com` miss → **new user 43** is created.

This is the safe outcome. "Link my accounts" requires explicit, authenticated proof of both mailboxes and is deferred to a future feature. The template spec documents this edge case clearly so operators are not surprised.

### 4.3 Identity lifecycle

- Revoke Google access → delete identity row 1. User can still log in via OTP (row 2).
- Drop email OTP → delete identity row 2. User can still log in via Google.
- Delete user → `ON DELETE CASCADE` removes both identity rows and all `user_roles` entries.

---

## 5. Backend architecture

### 5.1 Module layout

```
backend/app/
  auth/
    __init__.py
    models.py          # User, Role, UserRole, AuthIdentity
    schemas.py         # Pydantic: OtpRequest, OtpVerify, MeResponse, etc.
    router.py          # /auth/me, /auth/logout, /auth/otp/*, /auth/google/*
    service.py         # Session create/revoke, OTP gen/verify, OAuth code exchange
    sessions.py        # Redis session store (get/put/delete/extend, reverse index)
    otp.py             # OTP code generation, hashing, rate limit keys
    google.py          # OAuth state/PKCE helpers, JWKS verification
    email/
      __init__.py
      base.py          # EmailSender protocol
      console.py       # ConsoleEmailSender  (dev-only)
      resend.py        # ResendEmailSender   (prod)
      factory.py       # select by EMAIL_PROVIDER env var
    dependencies.py    # current_user, require_roles, require_authenticated
    bootstrap.py       # ADMIN_EMAILS grant-on-first-login hook
  middleware.py        # + SessionMiddleware
```

Email senders live under `app/auth/email/` since OTP is currently the only consumer. If a later feature needs transactional email for other purposes, the package hoists to `app/email/` with no other refactor.

### 5.2 Endpoint inventory

| Method + path | Feature | Purpose | Auth required |
|---|---|---|---|
| `POST /api/v1/auth/otp/request` | 002 | Send OTP to email | no |
| `POST /api/v1/auth/otp/verify` | 002 | Verify OTP → session | no |
| `GET /api/v1/auth/google/start` | 003 | Redirect to Google | no |
| `GET /api/v1/auth/google/callback` | 003 | Google redirect back → session | no |
| `GET /api/v1/auth/me` | 001 | Current user + roles | yes |
| `POST /api/v1/auth/logout` | 001 | Revoke session | yes |

### 5.3 FastAPI dependency examples (verbatim in spec)

```python
from app.auth.dependencies import current_user, require_roles

@router.get("/me")
async def me(user: User = Depends(current_user)) -> MeResponse: ...

@router.get("/admin/users")
async def list_users(user: User = Depends(require_roles("admin"))) -> ...: ...

@router.get("/public/hello")   # no Depends — public
async def hello(): ...
```

### 5.4 Middleware order (in `app/main.py`)

```
RequestIDMiddleware   (existing)
LoggingMiddleware     (existing)
SessionMiddleware     (new)
```

`SessionMiddleware` runs before the route, attaches `request.state.auth = AuthContext(...) | None`.

---

## 6. Data model

### 6.1 Postgres schema (Alembic migration in `feat_auth_001/versions/0002_create_auth.py`)

```sql
CREATE EXTENSION IF NOT EXISTS citext;

users (
  id              bigserial PRIMARY KEY,
  email           citext NOT NULL UNIQUE,
  display_name    varchar(255),
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_login_at   timestamptz
)

roles (
  id    serial PRIMARY KEY,
  name  varchar(64) NOT NULL UNIQUE
)
-- seeded by migration: INSERT INTO roles (name) VALUES ('admin'), ('user');

user_roles (
  user_id    bigint   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id    integer  NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
)

auth_identities (
  id                  bigserial PRIMARY KEY,
  user_id             bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider            varchar(32) NOT NULL,   -- 'email' | 'google'
  provider_user_id    varchar(255) NOT NULL,  -- Google 'sub' | email-itself
  email_at_identity   citext NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  last_used_at        timestamptz,
  UNIQUE (provider, provider_user_id)
)
CREATE INDEX ON auth_identities (user_id);
```

**Choice notes:**
- `citext` for case-insensitive email uniqueness.
- `ON DELETE CASCADE` user → identities, user → user_roles. `RESTRICT` on role deletion to prevent accidental nuking of `admin`.
- `email_at_identity` records what the provider saw at linking time; `users.email` is the canonical current email. They can drift over time (e.g., Google email changes after a rebrand). No auto-sync; user edits are a future feature.

### 6.2 Redis keyspaces (all TTL'd, no manual cleanup)

| Key pattern | Value | TTL | Set by | Feature |
|---|---|---|---|---|
| `session:<32-byte-hex>` | JSON `{user_id, email, roles[], created_at}` | 86400 | login success | 001 |
| `user_sessions:<user_id>` | SET of session ids | matches longest session | login success | 001 |
| `otp:<email_hash>` | JSON `{code_hash, attempts, created_at}` | 600 | OTP request | 002 |
| `otp_rate:<email_hash>:minute` | counter | 60 | OTP request | 002 |
| `otp_rate:<email_hash>:hour` | counter | 3600 | OTP request | 002 |
| `oauth_state:<state>` | JSON `{pkce_verifier, created_at, redirect_after}` | 600 | `/google/start` | 003 |

`<email_hash>` = `sha256(lower(email))` hex. Prevents plaintext emails leaking into Redis keys.

Session ID = `secrets.token_hex(32)` — 256 bits, opaque.

OTP codes stored as bcrypt hashes; work factor tuned for ~10ms verify (low because the search space is only 1M).

`oauth_state` consumed via `GETDEL` — single-use, prevents replay.

### 6.3 Alembic migrations across features

- `feat_auth_001`: `0002_create_auth.py` — all four tables at once, role seed, `citext` extension.
- `feat_auth_002`: no migration (everything lives in Redis).
- `feat_auth_003`: no migration (identities table exists).

---

## 7. Data flow — worked scenarios

### 7.1 Email OTP: request → verify → session

**Request.**

```
POST /api/v1/auth/otp/request   { "email": "alice@x.com" }
```

1. Normalize email, compute `h = sha256(lower(email))`.
2. Rate-limit check: `INCR otp_rate:<h>:minute` (>1 → 429); `INCR otp_rate:<h>:hour` (>10 → 429).
3. Generate `code = f"{secrets.randbelow(10**6):06d}"` → `"482913"`. Bcrypt-hash.
4. `SET otp:<h> '{"code_hash":"...","attempts":0,"created_at":...}' EX 600`.
5. Send email (`console` or `resend` provider).
6. Respond `204 No Content`. **Same response for known and unknown emails** — prevents account enumeration.

**Verify.**

```
POST /api/v1/auth/otp/verify   { "email": "alice@x.com", "code": "482913" }
```

1. `GET otp:<h>`. Missing → 400 `invalid_or_expired_code`.
2. `attempts >= 5` → 400 AND `DEL otp:<h>` (one-shot lockout).
3. `bcrypt.verify(code, code_hash)`:
   - Mismatch → increment `attempts`, preserve TTL, 400 `invalid_or_expired_code`.
   - Match → proceed.
4. `DEL otp:<h>` (one-shot, prevents replay).
5. Find-or-create user:
   - Identity `(email, alice@x.com)` → if found, `user = identity.user`.
   - Else user-by-email → if found, create identity (auto-link).
   - Else create user + identity + grant `user` role (+`admin` if in `ADMIN_EMAILS`).
6. `last_login_at = now()`; `last_used_at = now()` on identity.
7. Create session (§7.4).
8. `200` with `Set-Cookie: session=...` and body `{ "user": {...} }`.

**Failure matrix.**

| Condition | Code | Body |
|---|---|---|
| Rate limit hit | 429 | `{"detail": "too_many_requests", "retry_after": 42}` |
| Code expired / never requested | 400 | `{"detail": "invalid_or_expired_code"}` |
| Wrong code | 400 | `{"detail": "invalid_or_expired_code"}` |
| Attempts exhausted | 400 | `{"detail": "invalid_or_expired_code"}` |
| Deactivated user | 403 | `{"detail": "account_disabled"}` |

All four bad-code conditions return the same body string so an attacker can't distinguish "never requested" from "wrong code."

### 7.2 Google OAuth: start → callback → session

**Start.**

```
GET /api/v1/auth/google/start?redirect_after=/dashboard
```

1. `state = secrets.token_urlsafe(32)`, `pkce_verifier = secrets.token_urlsafe(64)`, `pkce_challenge = base64url(sha256(pkce_verifier))`.
2. `SET oauth_state:<state> '{"pkce_verifier":"...","redirect_after":"/dashboard"}' EX 600`.
3. Build Google auth URL and `302` redirect:

```
https://accounts.google.com/o/oauth2/v2/auth?
  client_id=<GOOGLE_OAUTH_CLIENT_ID>
  &redirect_uri=<GOOGLE_OAUTH_REDIRECT_URI>
  &response_type=code
  &scope=openid%20email%20profile
  &state=<state>
  &code_challenge=<pkce_challenge>
  &code_challenge_method=S256
  &prompt=select_account
```

**Callback.**

```
GET /api/v1/auth/google/callback?code=4/0Adeu5...&state=<state>
```

1. `GETDEL oauth_state:<state>` — atomic single-use. Missing → 400.
2. Parse `pkce_verifier` and `redirect_after` from the retrieved blob.
3. POST to `https://oauth2.googleapis.com/token` with `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`, `code_verifier=<pkce_verifier>`.
4. Verify the returned `id_token`:
   - Fetch Google JWKS from `https://www.googleapis.com/oauth2/v3/certs` (in-process cache, 10 min).
   - Verify RS256 signature against matching `kid`.
   - `iss` ∈ `{"https://accounts.google.com", "accounts.google.com"}`.
   - `aud == GOOGLE_OAUTH_CLIENT_ID`.
   - `exp > now()`.
   - Extract `sub`, `email`, `email_verified`, `name`.
5. **If `email_verified != true` → 400 `unverified_google_email`.** Never auto-link an unverified email.
6. Find-or-create user:
   - Identity `(google, sub)` → if found, `user = identity.user`.
   - Else user-by-email → if found, create identity (auto-link).
   - Else create user + identity + grant `user` role (+`admin` if in `ADMIN_EMAILS`).
7. Update `last_login_at`, `last_used_at`.
8. Create session (§7.4).
9. `302` redirect to `FRONTEND_URL + redirect_after` (defaulting to `/`), with `Set-Cookie: session=...`.

**Failure matrix.**

| Condition | Response |
|---|---|
| `state` missing or already consumed | `400 invalid_or_expired_state` + redirect to `FRONTEND_URL/login?error=expired` |
| Google token exchange fails | `400 google_token_exchange_failed` |
| ID token signature/claims invalid | `400 invalid_id_token` |
| `email_verified=false` | `400 unverified_google_email` |
| Account deactivated | `403 account_disabled` |

### 7.3 `/auth/me` on every subsequent request

```
GET /api/v1/auth/me
Cookie: session=abc123...
```

`SessionMiddleware` (every request, pre-route):
1. Read cookie. Absent → `request.state.auth = None`.
2. `GET session:abc123...`. Missing → clear cookie (`Max-Age=0`), `request.state.auth = None`.
3. Parse JSON → `request.state.auth = AuthContext(user_id=42, email='alice@x.com', roles=['user','admin'], session_id='abc123')`.
4. **No DB hit.**

`current_user` returns `request.state.auth` or raises 401. Response:

```json
{
  "user_id": 42,
  "email": "alice@x.com",
  "display_name": "Alice Smith",
  "roles": ["user", "admin"]
}
```

### 7.4 Session creation (shared helper)

```python
session_id = secrets.token_hex(32)
payload = {
    "user_id": user.id,
    "email": user.email,
    "roles": [r.name for r in user.roles],
    "created_at": now_iso(),
}
pipeline = redis.pipeline()
pipeline.set(f"session:{session_id}", json.dumps(payload), ex=86400)
pipeline.sadd(f"user_sessions:{user.id}", session_id)
pipeline.expire(f"user_sessions:{user.id}", 86400)
pipeline.execute()

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

`SESSION_COOKIE_SECURE=true` in staging/prod; `false` in local dev so http://localhost works. All three values (`name`, `ttl`, `secure`) come from `Settings` — no duplicated constants.

### 7.5 Logout

```
POST /api/v1/auth/logout   (authenticated)
```

1. `session_id = request.state.auth.session_id`.
2. `DEL session:<session_id>`.
3. `SREM user_sessions:<user_id> <session_id>`.
4. `204 No Content` with `Set-Cookie: session=; Max-Age=0`.

### 7.6 Role-change session revocation

Not a user-facing endpoint in the MVP. Service helper exists from day one:

```python
def revoke_sessions_for_user(user_id: int) -> None:
    session_ids = redis.smembers(f"user_sessions:{user_id}")
    if session_ids:
        redis.delete(*[f"session:{sid}" for sid in session_ids])
    redis.delete(f"user_sessions:{user_id}")
```

**We revoke, not update.** Simpler, predictable, no race conditions. User re-logs in with fresh roles.

### 7.7 `ADMIN_EMAILS` bootstrap

Parse once at startup into a lower-cased set. On user creation:

```python
if user.email.lower() in settings.admin_emails_set:
    user.roles.append(role_admin)
```

Empty env var → empty set → never grants admin. That is the normal state for a dev-only clone.

Demoting an admin: remove from the env var **and** `DELETE FROM user_roles WHERE user_id=X AND role_id=<admin>`. The env var is a first-login convenience, not a live sync. Documented explicitly in the deployment guide.

---

## 8. Security posture

### 8.1 In-scope defenses

| Threat | Mitigation |
|---|---|
| Session theft via XSS | httpOnly cookie — JS can't read |
| CSRF on auth endpoints | `SameSite=Lax` + JSON-only content-type check |
| Session replay after logout | Redis `DEL` on logout revokes instantly |
| Session hijack survives role change | `revoke_sessions_for_user` helper |
| OTP brute force | bcrypt-hashed codes, 5-attempt lockout, 10-min TTL, rate limits |
| OTP enumeration | Same 204 response for known and unknown emails |
| OAuth code replay | `state` consumed via `GETDEL` |
| OAuth MITM on code exchange | PKCE (S256) — attacker can't exchange intercepted code |
| Unverified Google email hijack | Reject `email_verified=false` |
| Admin privilege escalation | `ADMIN_EMAILS` env-gated, no self-service admin endpoint |
| Cookie over plaintext | `Secure=True` in non-dev envs |
| Redis session leak via `KEYS *` | Emails hashed in keys; session payloads minimal |
| Stored OTP compromise | Codes stored as bcrypt hash, not plaintext |

### 8.2 Out of scope (document, don't build)

- MFA / TOTP beyond OTP email.
- Password login (passwordless by design).
- Account recovery beyond "request another OTP."
- Anti-CSRF tokens on non-auth routes (add when first mutating non-auth route lands).
- Full audit log. `last_login_at` + `last_used_at` + structured logs are the MVP trail.
- Account linking UI.
- User profile editing, admin dashboard, second OAuth provider, email templating, session "devices" view, password reset, account self-deletion.

---

## 9. Testing strategy

### 9.1 Backend unit tests (`backend/tests/`)

| Area | Sample cases |
|---|---|
| `otp.generate_code` / `otp.verify_code` | 6 digits, bcrypt roundtrip, attempt increment, TTL preserved after mismatch, one-shot delete on success |
| `sessions.create` / `get` / `delete` | Payload round-trip, reverse index updated, `delete` wipes both keys |
| `google.verify_id_token` | Valid signed token passes; expired rejected; wrong `aud` rejected; wrong `iss` rejected; `email_verified=false` rejected — using a fixture JWKS + signed tokens, not the real Google |
| `bootstrap.grant_admin_if_listed` | Matching email grants admin; non-matching doesn't; empty list no-op |
| `dependencies.current_user` | Missing cookie → 401; valid → user; expired session → 401 |
| `dependencies.require_roles` | Role present → pass; role missing → 403; multiple roles OR semantics |
| OTP rate limiter | 2nd request within 60s blocked; 61s later allowed; 11th within hour blocked |

### 9.2 Backend integration tests (real Postgres + Redis)

| Flow | Assertions |
|---|---|
| OTP request → verify → `/me` → logout → `/me` 401 | Full session lifecycle |
| OTP with wrong code 5× → 6th is locked even with correct code → new request works | Lockout semantics |
| Google callback with stubbed token endpoint + test-keypair JWKS | Full OAuth happy path end-to-end |
| Same email via Google then OTP (§4.1) | Two identity rows, one user |
| `ADMIN_EMAILS=alice@x.com` → Alice's first login grants admin | Bootstrap works |

### 9.3 External REST suite (`test.sh` extensions)

- `POST /auth/otp/request` → 204; `POST /auth/otp/verify` → 200 with `Set-Cookie`.
- Cookie-bearing `GET /auth/me` → 200; no-cookie → 401.
- `POST /auth/logout` → 204; follow-up `/auth/me` → 401.
- Google flow: mock Google server run inside the test container verifies `302 → callback → 302 FRONTEND_URL` shape.

### 9.4 Frontend tests (`feat_frontend_002`)

- Login page renders both options.
- OTP form — submit, receive code (dev pulls from backend log), verify, land on home with user state.
- Protected-route wrapper redirects unauthenticated to `/login`.
- Logout button clears state and redirects.

---

## 10. Observability

Structured log events emitted via the existing structlog chain from `feat_backend_002`. Event names are stable; fields are consistent across all auth flows.

```
auth.otp.requested     email_hash=<h>   rate_bucket_minute=1  provider=email
auth.otp.verified      user_id=42       email_hash=<h>        new_user=false
auth.otp.failed        email_hash=<h>   reason=invalid_code   attempts=2
auth.google.started    state_hash=<h>
auth.google.callback   user_id=42       email_hash=<h>        new_user=true   linked=google
auth.google.failed     reason=email_unverified
auth.session.created   user_id=42       session_id_hash=<h>
auth.session.revoked   user_id=42       session_id_hash=<h>   reason=logout
auth.role.granted      user_id=42       role=admin            source=admin_emails_bootstrap
```

**Rules:**
- Never log full emails or session IDs — always `sha256(x)[:16]` as `*_hash`. Consistent across events for the same principal. Log-trace-able without PII.
- Never log OTP codes or Google tokens (except the `ConsoleEmailSender`, which is the intentional dev-only exception).
- Every failure carries a `reason` field with a short, stable enum value. Greppable.
- Every flow terminator emits exactly one success or one failure event. No silent successes.

---

## 11. Environment variables

Added to `infra/.env.example`:

```ini
# ---- Auth (feat_auth_001) ----
SESSION_COOKIE_NAME=session
SESSION_TTL_SECONDS=86400
SESSION_COOKIE_SECURE=false          # override to true in staging/prod
ADMIN_EMAILS=                        # comma-separated; empty = no bootstrap admin

# ---- Email / OTP (feat_auth_002) ----
EMAIL_PROVIDER=console               # 'console' | 'resend'
EMAIL_FROM="minimalist-app <noreply@example.com>"
RESEND_API_KEY=                      # required when EMAIL_PROVIDER=resend
OTP_CODE_TTL_SECONDS=600
OTP_MAX_ATTEMPTS=5
OTP_RATE_PER_MINUTE=1
OTP_RATE_PER_HOUR=10

# ---- Google OAuth (feat_auth_003) ----
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
FRONTEND_URL=http://localhost:5173
```

All parsed into `app/settings.py` via Pydantic Settings. Defaults are chosen so `make up` on a clean clone **works out of the box for OTP-via-console** — no external signups required to develop. Google requires the three `GOOGLE_OAUTH_*` fields populated per the deployment guide.

---

## 12. Redis persistence (compose edit)

`infra/docker-compose.yml` — `redis` service (edit lands in `feat_auth_001`):

```yaml
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --appendonly yes
    --appendfsync everysec
  volumes:
    - redis-data:/data
```

Plus the `redis-data` named volume. Survives routine restarts. Session continuity across `make down && make up` within a second or two of the last write.

---

## 13. Deployment documentation

New directory: `docs/deployment/`. Separate from the top-level `deployment/` path (reserved by `conventions.md` §8 for Helm/Terraform artifacts).

**`docs/deployment/README.md`** — one-screen index:

> External services that need manual setup before production. Each guide is self-contained and lists the env vars it populates.
>
> - [Google OAuth](google-oauth-setup.md) — required for `feat_auth_003` (Sign in with Google).
> - [Email / OTP](email-otp-setup.md) — required for `feat_auth_002` in non-dev envs (Sign in with email OTP).

**`docs/deployment/google-oauth-setup.md`** (lands with `feat_auth_003`):

- Prerequisites.
- Step 1: Create or select GCP project.
- Step 2: Configure OAuth consent screen (user type, scopes, test users).
- Step 3: Create OAuth 2.0 Client ID (web application type, redirect URIs for dev + prod).
- Step 4: Populate `.env` — copy Client ID + Client Secret; exact var names.
- Step 5: Verify — `make up`, navigate to `/api/v1/auth/google/start`, confirm redirect dance.
- Troubleshooting table: redirect URI mismatch; test user 403; consent screen in Testing mode expired; token exchange fail; client secret rotation.
- Rotating credentials.

**`docs/deployment/email-otp-setup.md`** (lands with `feat_auth_002`):

- Provider comparison table (Resend / SendGrid / SES / Postmark — 4 rows × price/ease/region).
- Why the template defaults to Resend (simplest API, free tier).
- Step 1: Create Resend account, verify sending domain (DKIM + SPF DNS records).
- Step 2: Generate API key.
- Step 3: Populate `.env` — `EMAIL_PROVIDER=resend`, `RESEND_API_KEY=...`, `EMAIL_FROM="..."`.
- Step 4: Verify — hit `/auth/otp/request`, confirm email lands, check DKIM pass in headers.
- Troubleshooting table: email in spam; DKIM fail; sender-not-verified; Resend rate limit; switching to SendGrid.
- Rotating credentials.

---

## 14. Convention updates (inside `feat_auth_001`)

- `conventions.md` §1 — add the `auth` row to the domains table.
- `conventions.md` §8 — **no** change to `deployment/` reservation (we're using `docs/deployment/` instead).
- `conventions.md` §10 — leave the "initial feature roster" label alone; the four new features live under `docs/tracking/features.md` instead.
- `docs/tracking/features.md` — one row per feature, statuses advance through the usual `Planned → In Spec → Ready → In Build → Merged` lifecycle.

---

## 15. Explicit non-goals

The following are deliberately **not** in this four-feature sequence. Raising any of them mid-implementation → push back and propose as a future feature.

- User profile editing (change email, display name).
- Account linking UI (§4.2 edge case).
- Admin dashboard or admin UI.
- Second OAuth provider (GitHub, Apple, Microsoft).
- Email templating system — OTP body is a string literal.
- Session "devices" view.
- Password reset / passwords generally.
- Account self-deletion.
- MFA / TOTP.
- Full audit log.

---

## 16. Implementation sequencing reminder

Per `conventions.md` §§3–5 and the existing AutoDev workflow:

1. **Atlas** plans `feat_auth_001` first — writes the three spec files on `spec/feat_auth_001`, opens spec PR. Merges to `main`.
2. **Vulcan** implements on `build/feat_auth_001`. Merges.
3. Repeat for `feat_auth_002`, then `feat_auth_003`, then `feat_frontend_002`.

This design document serves as the stable source of truth across all four planning cycles. If any of the four atlas sessions wants to deviate from this design, that deviation is a revision of this document first, spec second.
