"""Endpoint tests for ``POST /api/v1/auth/otp/verify``.

Uses the ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE`` fixture so verify is
deterministic without log-scraping. Asserts:

- Happy path with new user creates exactly one users + one auth_identities
  + one user_roles row (``user``).
- The four bad-code conditions (missing, expired, wrong, exhausted) all
  return the same uniform body.
- One-shot on success, attempts lockout, ``ADMIN_EMAILS`` bootstrap,
  auto-link of an existing user, and cookie attributes.
- The deleted ``_test/session`` endpoint is not reachable, and the
  legacy symbols are not importable.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth import otp, otp_store
from app.auth.models import AuthIdentity, Role, User, UserRole
from app.db import build_sessionmaker
from app.main import create_app
from app.settings import Settings


_TEST_EMAIL = "alice@x.com"
_TEST_CODE = "123456"


def _settings(**overrides) -> Settings:
    defaults: dict = dict(
        env="test",
        test_otp_email=_TEST_EMAIL,
        test_otp_code=_TEST_CODE,
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
async def build_client(require_db, require_redis, clean_db):
    opened: list = []

    async def _open(settings: Settings):
        app = create_app(settings)
        cm = app.router.lifespan_context(app)
        await cm.__aenter__()
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


async def _request(client: AsyncClient, email: str = _TEST_EMAIL):
    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": email}
    )
    assert r.status_code == 204, r.text


async def test_happy_path_new_user(build_client, require_db):
    app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["email"] == _TEST_EMAIL
    assert body["display_name"] is None
    assert body["roles"] == ["user"]

    # Cookie attributes.
    sc = r.headers.get("set-cookie", "")
    assert "HttpOnly" in sc
    assert "SameSite=Lax" in sc or "samesite=lax" in sc.lower()
    assert "Path=/" in sc
    assert "Max-Age=86400" in sc or "max-age=86400" in sc.lower()

    # Database: exactly one users + one identity + one user_role.
    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            users = (
                await session.execute(
                    select(User).where(User.email == _TEST_EMAIL)
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
            assert len(identities) == 1
            assert identities[0].provider == "email"
            assert identities[0].provider_user_id == _TEST_EMAIL
            assert identities[0].email_at_identity == _TEST_EMAIL

            role_rows = (
                await session.execute(
                    select(Role.name)
                    .select_from(UserRole)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(UserRole.user_id == users[0].id)
                )
            ).all()
            names = {n for (n,) in role_rows}
            assert names == {"user"}
    finally:
        await engine.dispose()


async def test_me_round_trip_after_verify(build_client):
    _app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200
    sc = r.headers.get("set-cookie", "")
    sid = sc.split(";", 1)[0].split("=", 1)[1]

    me = await client.get(
        "/api/v1/auth/me", cookies={"session": sid}
    )
    assert me.status_code == 200
    assert me.json()["email"] == _TEST_EMAIL


async def test_wrong_code_uniform_400(build_client):
    app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": "999999"},
    )
    assert r.status_code == 400
    body = r.json()
    # Envelope shape from feat_backend_002; the detail we set on
    # ``HTTPException`` lives at ``error.message``.
    assert body["error"]["message"] == "invalid_or_expired_code"

    record = await otp_store.load_otp(_TEST_EMAIL, redis=app.state.redis)
    assert record is not None
    assert record.attempts == 1


async def test_attempts_lockout(build_client):
    app, client = await build_client(_settings())

    await _request(client)
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/otp/verify",
            json={"email": _TEST_EMAIL, "code": "999999"},
        )
        assert r.status_code == 400

    # 6th call with the correct code -- still 400, record now deleted.
    r6 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r6.status_code == 400
    assert await otp_store.load_otp(_TEST_EMAIL, redis=app.state.redis) is None


async def test_one_shot_on_success(build_client):
    _app, client = await build_client(_settings())

    await _request(client)
    r1 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r1.status_code == 200

    # Second verify with the same (now consumed) code -> 400.
    r2 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r2.status_code == 400


async def test_never_requested_email(build_client):
    _app, client = await build_client(_settings())

    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "bob@x.com", "code": _TEST_CODE},
    )
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "invalid_or_expired_code"


async def test_expired_otp(build_client):
    app, client = await build_client(_settings())

    await _request(client)
    # Simulate TTL expiry by deleting the key.
    await app.state.redis.delete(otp.otp_key(_TEST_EMAIL))

    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 400


async def test_non_six_digit_code_is_400_not_422(build_client):
    _app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": "1234"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "invalid_or_expired_code"


async def test_non_digit_code_is_400(build_client):
    _app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": "abcdef"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "invalid_or_expired_code"


async def test_case_insensitive_email_on_verify(build_client, require_db):
    _app, client = await build_client(_settings())

    # Request with mixed case; verify with lowercase.
    r1 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "Alice@X.com"}
    )
    assert r1.status_code == 204

    r2 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r2.status_code == 200


async def test_auto_link_existing_user(build_client, require_db):
    """Seed a user row by hand; first OTP verify links a new identity."""

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            session.add(User(email=_TEST_EMAIL, display_name="Preset"))
            await session.commit()
    finally:
        await engine.dispose()

    app, client = await build_client(_settings())
    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Preset"

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            users = (
                await session.execute(
                    select(User).where(User.email == _TEST_EMAIL)
                )
            ).scalars().all()
            assert len(users) == 1  # no duplicate

            identities = (
                await session.execute(
                    select(AuthIdentity).where(
                        AuthIdentity.user_id == users[0].id
                    )
                )
            ).scalars().all()
            assert len(identities) == 1
            assert identities[0].provider == "email"
    finally:
        await engine.dispose()


async def test_reuse_existing_email_identity(build_client, require_db):
    """Two OTP logins for the same email do not duplicate identity rows."""

    app, client = await build_client(_settings())
    await _request(client)
    r1 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r1.status_code == 200

    await _request(client)
    r2 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r2.status_code == 200

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            users = (
                await session.execute(
                    select(User).where(User.email == _TEST_EMAIL)
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
            assert len(identities) == 1
    finally:
        await engine.dispose()


async def test_admin_emails_bootstrap_on_first_login(build_client):
    _app, client = await build_client(
        _settings(admin_emails=_TEST_EMAIL)
    )

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200
    roles = set(r.json()["roles"])
    assert roles == {"user", "admin"}


async def test_second_login_does_not_duplicate_roles(
    build_client, require_db
):
    _app, client = await build_client(
        _settings(admin_emails=_TEST_EMAIL)
    )

    await _request(client)
    r1 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r1.status_code == 200

    await _request(client)
    r2 = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r2.status_code == 200

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            users = (
                await session.execute(
                    select(User).where(User.email == _TEST_EMAIL)
                )
            ).scalars().all()
            assert len(users) == 1
            role_rows = (
                await session.execute(
                    select(UserRole).where(UserRole.user_id == users[0].id)
                )
            ).scalars().all()
            assert len(role_rows) == 2
    finally:
        await engine.dispose()


async def test_cookie_secure_attribute_reflects_settings(build_client):
    _app, client = await build_client(
        _settings(session_cookie_secure=True)
    )

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200
    assert "Secure" in r.headers.get("set-cookie", "")


async def test_verify_failure_does_not_create_user(build_client, require_db):
    app, client = await build_client(_settings())

    await _request(client)
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": "999999"},
    )
    assert r.status_code == 400

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with sm() as session:
            rows = (
                await session.execute(select(User))
            ).scalars().all()
            assert rows == []
    finally:
        await engine.dispose()


async def test_test_session_endpoint_is_404(build_client):
    _app, client = await build_client(_settings())
    r = await client.post(
        "/api/v1/_test/session", json={"email": "x@x.com"}
    )
    assert r.status_code == 404


def test_removed_symbols_are_not_importable():
    """The three symbols that belonged to the old mint endpoint are gone."""

    with pytest.raises(ImportError):
        from app.auth.schemas import TestSessionRequest  # noqa: F401

    with pytest.raises(ImportError):
        from app.auth.service import find_or_create_user_for_test  # noqa: F401

    with pytest.raises(ImportError):
        from app.auth.router import test_router  # noqa: F401
