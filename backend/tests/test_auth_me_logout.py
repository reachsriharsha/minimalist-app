"""End-to-end tests for the ``/auth/me`` + ``/auth/logout`` pair.

Exercises the full lifecycle through the env-gated test-only mint endpoint:

mint → /auth/me → /auth/logout → /auth/me (401).

Also covers ``ADMIN_EMAILS`` bootstrap, extra-roles parameter, idempotent
mint, cookie attributes, and ``revoke_sessions_for_user`` end-to-end.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth import service
from app.auth.models import AuthIdentity, User
from app.db import build_sessionmaker
from app.main import create_app
from app.settings import Settings, reset_settings_cache


@pytest.fixture
async def clean_db(require_db) -> str:
    """Return the DB URL after truncating the auth tables."""

    engine = create_async_engine(require_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE auth_identities, user_roles, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()
    return require_db


async def _build_client(settings: Settings):
    app = create_app(settings)
    return app, app.router.lifespan_context(app)


@pytest.fixture
async def client_for_settings(require_db, require_redis, clean_db):
    """Factory that builds an ``httpx`` client for a given Settings."""

    opened: list = []

    async def _open(settings: Settings):
        reset_settings_cache()
        app = create_app(settings)
        cm = app.router.lifespan_context(app)
        await cm.__aenter__()
        # Scrub redis between builds.
        await app.state.redis.flushdb()
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        await client.__aenter__()
        opened.append((app, cm, client))
        return app, client

    yield _open

    for app, cm, client in opened:
        try:
            await client.__aexit__(None, None, None)
        finally:
            await cm.__aexit__(None, None, None)


def _cookie_from(resp) -> str:
    set_cookie = resp.headers.get("set-cookie") or ""
    pairs = set_cookie.split(";")
    first = pairs[0].strip()
    assert first.startswith("session="), set_cookie
    return first.removeprefix("session=")


async def test_happy_path_mint_me_logout_me(client_for_settings):
    _app, client = await client_for_settings(Settings(env="test"))

    # 1. Mint
    mint = await client.post(
        "/api/v1/_test/session",
        json={"email": "a@x.com", "display_name": "Alice"},
    )
    assert mint.status_code == 200, mint.text
    sid = _cookie_from(mint)
    body = mint.json()
    assert body["email"] == "a@x.com"
    assert body["display_name"] == "Alice"
    assert body["roles"] == ["user"]

    # 2. /auth/me (1)
    me1 = await client.get(
        "/api/v1/auth/me", cookies={"session": sid}
    )
    assert me1.status_code == 200
    b1 = me1.json()
    assert b1["email"] == "a@x.com"
    assert b1["display_name"] == "Alice"
    assert b1["roles"] == ["user"]

    # 3. /auth/logout
    logout = await client.post(
        "/api/v1/auth/logout", cookies={"session": sid}
    )
    assert logout.status_code == 204
    # Cookie cleared.
    set_cookie = logout.headers.get("set-cookie") or ""
    assert "session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()

    # 4. /auth/me (2) — session is gone.
    me2 = await client.get(
        "/api/v1/auth/me", cookies={"session": sid}
    )
    assert me2.status_code == 401


async def test_admin_emails_bootstrap(client_for_settings):
    _app, client = await client_for_settings(
        Settings(env="test", admin_emails="alice@x.com")
    )

    mint = await client.post(
        "/api/v1/_test/session",
        json={"email": "alice@x.com"},
    )
    assert mint.status_code == 200, mint.text
    sid = _cookie_from(mint)

    me = await client.get("/api/v1/auth/me", cookies={"session": sid})
    assert me.status_code == 200
    roles = set(me.json()["roles"])
    assert roles == {"user", "admin"}


async def test_non_bootstrap_user_only_gets_user(client_for_settings):
    _app, client = await client_for_settings(
        Settings(env="test", admin_emails="alice@x.com")
    )

    mint = await client.post(
        "/api/v1/_test/session",
        json={"email": "bob@x.com"},
    )
    assert mint.status_code == 200
    sid = _cookie_from(mint)

    me = await client.get("/api/v1/auth/me", cookies={"session": sid})
    assert me.status_code == 200
    assert me.json()["roles"] == ["user"]


async def test_extra_roles_parameter(client_for_settings):
    _app, client = await client_for_settings(Settings(env="test"))

    mint = await client.post(
        "/api/v1/_test/session",
        json={"email": "a@x.com", "roles": ["admin"]},
    )
    assert mint.status_code == 200, mint.text
    sid = _cookie_from(mint)

    me = await client.get("/api/v1/auth/me", cookies={"session": sid})
    assert me.status_code == 200
    roles = set(me.json()["roles"])
    # User always granted as the default; admin granted via extra_roles.
    assert roles == {"user", "admin"}


async def test_idempotent_mint(client_for_settings, require_db):
    _app, client = await client_for_settings(Settings(env="test"))

    r1 = await client.post(
        "/api/v1/_test/session",
        json={"email": "a@x.com"},
    )
    r2 = await client.post(
        "/api/v1/_test/session",
        json={"email": "a@x.com"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Exactly one users row and zero auth_identities rows for that email.
    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            users = (
                await session.execute(
                    select(User).where(User.email == "a@x.com")
                )
            ).scalars().all()
            assert len(users) == 1

            identities = (
                await session.execute(
                    select(AuthIdentity).where(
                        AuthIdentity.user_id == users[0].id
                    )
                )
            ).scalars().all()
            assert identities == []
    finally:
        await engine.dispose()


async def test_revoke_sessions_for_user_end_to_end(client_for_settings):
    app, client = await client_for_settings(Settings(env="test"))

    # Mint two sessions for the same user (two separate POSTs).
    m1 = await client.post(
        "/api/v1/_test/session", json={"email": "a@x.com"}
    )
    sid_a = _cookie_from(m1)

    m2 = await client.post(
        "/api/v1/_test/session", json={"email": "a@x.com"}
    )
    sid_b = _cookie_from(m2)

    assert sid_a != sid_b

    # Pull the user ID out of /auth/me.
    probe = await client.get(
        "/api/v1/auth/me", cookies={"session": sid_a}
    )
    user_id = probe.json()["user_id"]

    # Revoke every session for this user.
    await service.revoke_sessions_for_user(user_id, redis=app.state.redis)

    # Both cookies should now be dead.
    r1 = await client.get("/api/v1/auth/me", cookies={"session": sid_a})
    r2 = await client.get("/api/v1/auth/me", cookies={"session": sid_b})
    assert r1.status_code == 401
    assert r2.status_code == 401

    # Reverse index is gone.
    assert await app.state.redis.exists(f"user_sessions:{user_id}") == 0


async def test_no_cookie_me_returns_401(client_for_settings):
    _app, client = await client_for_settings(Settings(env="test"))
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "not_authenticated"


async def test_logout_without_session_is_401(client_for_settings):
    app, client = await client_for_settings(Settings(env="test"))
    redis = app.state.redis

    # Capture Redis commands by intercepting execute_command. The logout
    # handler should never reach the ``delete`` call on an unauthenticated
    # request — the ``current_user`` dependency short-circuits first.
    captured: list[str] = []
    orig = redis.execute_command

    async def spy(*args, **kwargs):
        captured.append(str(args[0]).upper() if args else "")
        return await orig(*args, **kwargs)

    redis.execute_command = spy  # type: ignore[assignment]
    try:
        resp = await client.post("/api/v1/auth/logout")
    finally:
        redis.execute_command = orig  # type: ignore[assignment]

    assert resp.status_code == 401
    # No DEL issued against any session key.
    assert not any(cmd == "DEL" for cmd in captured), captured


async def test_cookie_attributes_insecure(client_for_settings):
    _app, client = await client_for_settings(
        Settings(env="test", session_cookie_secure=False)
    )

    mint = await client.post(
        "/api/v1/_test/session", json={"email": "a@x.com"}
    )
    assert mint.status_code == 200
    sc = mint.headers.get("set-cookie", "")

    assert "HttpOnly" in sc
    assert "SameSite=Lax" in sc or "samesite=lax" in sc.lower()
    assert "Path=/" in sc
    # Max-Age matches the default settings.session_ttl_seconds (86400).
    assert "Max-Age=86400" in sc or "max-age=86400" in sc.lower()
    # Secure absent.
    assert "Secure" not in sc


async def test_cookie_attributes_secure(client_for_settings):
    _app, client = await client_for_settings(
        Settings(env="test", session_cookie_secure=True)
    )

    mint = await client.post(
        "/api/v1/_test/session", json={"email": "a@x.com"}
    )
    assert mint.status_code == 200
    sc = mint.headers.get("set-cookie", "")

    assert "Secure" in sc
