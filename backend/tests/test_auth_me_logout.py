"""End-to-end tests for the ``/auth/me`` + ``/auth/logout`` pair.

Exercises the full lifecycle through the real OTP flow (feat_auth_002):

  POST /auth/otp/request -> POST /auth/otp/verify -> /auth/me
    -> /auth/logout -> /auth/me (401).

Also covers ``ADMIN_EMAILS`` bootstrap, idempotent mint, cookie
attributes, and ``revoke_sessions_for_user`` end-to-end.

feat_auth_001's nine cases are preserved; only the "how do we get a
cookie" step changes. The ``extra_roles`` case (001's case 4) is
deleted because ``OtpVerifyIn`` does not accept caller-specified
roles -- real login paths never do.
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


_TEST_EMAIL = "melogout@x.com"
_TEST_CODE = "654321"


def _settings_for_email(email: str = _TEST_EMAIL, **overrides) -> Settings:
    """Build a ``Settings(env='test', ...)`` with the OTP fixture set."""

    defaults: dict = dict(
        env="test",
        test_otp_email=email,
        test_otp_code=_TEST_CODE,
        # Loosen rate limit for repeat mints within a single test.
        otp_rate_per_minute=100,
        otp_rate_per_hour=1000,
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
async def clean_db(require_db) -> str:
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


async def _mint_via_otp(
    client: AsyncClient, email: str = _TEST_EMAIL, code: str = _TEST_CODE
) -> tuple[str, dict]:
    """Mint a session via real OTP, return ``(session_id, verify_body)``."""

    req = await client.post(
        "/api/v1/auth/otp/request", json={"email": email}
    )
    assert req.status_code == 204, req.text

    ver = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": email, "code": code},
    )
    assert ver.status_code == 200, ver.text

    set_cookie = ver.headers.get("set-cookie", "")
    assert set_cookie.startswith("session=") or "session=" in set_cookie
    first = set_cookie.split(";", 1)[0]
    name, raw = first.split("=", 1)
    assert name.strip() == "session"
    return raw, ver.json()


async def test_happy_path_mint_me_logout_me(client_for_settings):
    _app, client = await client_for_settings(
        _settings_for_email("a@x.com")
    )

    # 1. Mint via OTP
    sid, body = await _mint_via_otp(client, email="a@x.com")
    assert body["email"] == "a@x.com"
    assert body["display_name"] is None
    assert body["roles"] == ["user"]

    # 2. /auth/me (1)
    me1 = await client.get(
        "/api/v1/auth/me", cookies={"session": sid}
    )
    assert me1.status_code == 200
    b1 = me1.json()
    assert b1["email"] == "a@x.com"
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

    # 4. /auth/me (2) -- session is gone.
    me2 = await client.get(
        "/api/v1/auth/me", cookies={"session": sid}
    )
    assert me2.status_code == 401


async def test_admin_emails_bootstrap(client_for_settings):
    _app, client = await client_for_settings(
        _settings_for_email("alice@x.com", admin_emails="alice@x.com")
    )

    sid, _ = await _mint_via_otp(client, email="alice@x.com")

    me = await client.get("/api/v1/auth/me", cookies={"session": sid})
    assert me.status_code == 200
    roles = set(me.json()["roles"])
    assert roles == {"user", "admin"}


async def test_non_bootstrap_user_only_gets_user(client_for_settings):
    _app, client = await client_for_settings(
        _settings_for_email("bob@x.com", admin_emails="alice@x.com")
    )

    sid, _ = await _mint_via_otp(client, email="bob@x.com")

    me = await client.get("/api/v1/auth/me", cookies={"session": sid})
    assert me.status_code == 200
    assert me.json()["roles"] == ["user"]


async def test_idempotent_mint(client_for_settings, require_db):
    """Two OTP cycles for the same email leave one users row + one identity."""

    _app, client = await client_for_settings(
        _settings_for_email("a@x.com")
    )

    sid1, _ = await _mint_via_otp(client, email="a@x.com")
    sid2, _ = await _mint_via_otp(client, email="a@x.com")
    assert sid1 != sid2

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
            # feat_auth_002 creates exactly one identity row on first
            # OTP login and reuses it on the second.
            assert len(identities) == 1
            assert identities[0].provider == "email"
            assert identities[0].provider_user_id == "a@x.com"
    finally:
        await engine.dispose()


async def test_revoke_sessions_for_user_end_to_end(client_for_settings):
    app, client = await client_for_settings(
        _settings_for_email("a@x.com")
    )

    # Mint two sessions for the same user (two separate OTP cycles).
    sid_a, _ = await _mint_via_otp(client, email="a@x.com")
    sid_b, _ = await _mint_via_otp(client, email="a@x.com")
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
    # request -- the ``current_user`` dependency short-circuits first.
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
    assert not any(cmd == "DEL" for cmd in captured), captured


async def test_cookie_attributes_insecure(client_for_settings):
    _app, client = await client_for_settings(
        _settings_for_email("a@x.com", session_cookie_secure=False)
    )

    req = await client.post(
        "/api/v1/auth/otp/request", json={"email": "a@x.com"}
    )
    assert req.status_code == 204
    ver = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "a@x.com", "code": _TEST_CODE},
    )
    assert ver.status_code == 200
    sc = ver.headers.get("set-cookie", "")

    assert "HttpOnly" in sc
    assert "SameSite=Lax" in sc or "samesite=lax" in sc.lower()
    assert "Path=/" in sc
    assert "Max-Age=86400" in sc or "max-age=86400" in sc.lower()
    # Secure absent.
    assert "Secure" not in sc


async def test_cookie_attributes_secure(client_for_settings):
    _app, client = await client_for_settings(
        _settings_for_email("a@x.com", session_cookie_secure=True)
    )

    req = await client.post(
        "/api/v1/auth/otp/request", json={"email": "a@x.com"}
    )
    assert req.status_code == 204
    ver = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "a@x.com", "code": _TEST_CODE},
    )
    assert ver.status_code == 200
    sc = ver.headers.get("set-cookie", "")

    assert "Secure" in sc
