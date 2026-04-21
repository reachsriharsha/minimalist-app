"""Integration tests for :class:`app.middleware.SessionMiddleware`.

Exercises the middleware behaviour end-to-end through
``httpx.AsyncClient``:

- No cookie -> request goes through with ``request.state.auth = None``.
- Valid cookie -> ``request.state.auth`` is populated from the Redis
  payload.
- Expired / malformed session -> 401 from the dependency,
  ``Set-Cookie`` clears the cookie, a log event is emitted.
- ``RequestIDMiddleware`` remains outermost (log event carries
  ``request_id``).

feat_auth_002 note: session-minting no longer goes through the test-only
``/api/v1/_test/session`` endpoint (deleted by this feature). We now
mint via ``POST /auth/otp/request`` + ``POST /auth/otp/verify`` with
the ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE`` fixture, which the router
uses to overwrite the stored hash so verify is deterministic.
"""

from __future__ import annotations

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import create_app
from app.settings import Settings, reset_settings_cache


_TEST_EMAIL = "middleware@x.com"
_TEST_CODE = "123456"


def _test_settings_with_fixture(**overrides) -> Settings:
    """Build a ``Settings(env='test', ...)`` with the OTP fixture vars set."""

    defaults: dict = dict(
        env="test",
        test_otp_email=_TEST_EMAIL,
        test_otp_code=_TEST_CODE,
        # Loosen rate limit so we can mint multiple sessions per test.
        otp_rate_per_minute=100,
        otp_rate_per_hour=1000,
    )
    defaults.update(overrides)
    return Settings(**defaults)


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


@pytest.fixture
def test_settings(require_db, require_redis) -> Settings:
    """Settings pinned to ``env=test`` with the OTP fixture configured."""

    reset_settings_cache()
    return _test_settings_with_fixture()


@pytest.fixture
async def app_and_client(test_settings, clean_db):
    app = create_app(test_settings)
    async with app.router.lifespan_context(app):
        # Also flush Redis so no state leaks across tests in this module.
        redis = app.state.redis
        await redis.flushdb()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield app, client
        await redis.flushdb()


async def test_no_cookie_public_endpoint_has_no_set_cookie(app_and_client):
    _app, client = app_and_client

    resp = await client.get("/healthz")

    assert resp.status_code == 200
    # No Set-Cookie at all -- public endpoint, no session work happened.
    assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}


async def _mint_via_otp(client: AsyncClient, email: str = _TEST_EMAIL) -> str:
    """Mint a session via the real OTP flow and return the ``session`` cookie.

    Requires the ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE`` fixture to be
    configured on the backend so verify succeeds with ``_TEST_CODE``.
    """

    req = await client.post(
        "/api/v1/auth/otp/request",
        json={"email": email},
    )
    assert req.status_code == 204, req.text

    ver = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": email, "code": _TEST_CODE},
    )
    assert ver.status_code == 200, ver.text

    set_cookie = ver.headers.get("set-cookie")
    assert set_cookie, "verify did not set a cookie"
    value = set_cookie.split(";", 1)[0]
    assert "=" in value
    name, raw = value.split("=", 1)
    assert name.strip() == "session"
    return raw


async def test_valid_cookie_populates_context(app_and_client):
    _app, client = app_and_client

    session_id = await _mint_via_otp(client, _TEST_EMAIL)

    # Now call /auth/me carrying the cookie and verify the payload the
    # middleware's context produced.
    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"session": session_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == _TEST_EMAIL
    assert "user" in body["roles"]


async def test_expired_session_clears_cookie(app_and_client):
    app, client = app_and_client
    redis = app.state.redis

    session_id = await _mint_via_otp(client, _TEST_EMAIL)

    # Simulate expiry by deleting the session key directly in Redis.
    await redis.delete(f"session:{session_id}")

    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"session": session_id},
    )
    assert resp.status_code == 401
    body = resp.json()
    # HTTPException(detail="not_authenticated") envelope-wrapped.
    assert body["error"]["message"] == "not_authenticated"

    # Set-Cookie clears the cookie.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "Max-Age=0" in set_cookie


async def test_malformed_payload_clears_cookie(app_and_client, caplog):
    app, client = app_and_client
    redis = app.state.redis

    session_id = await _mint_via_otp(client, _TEST_EMAIL)

    # Overwrite the session key with non-JSON to trigger the
    # ``malformed_payload`` branch.
    await redis.set(f"session:{session_id}", "not json")

    with caplog.at_level(logging.INFO):
        resp = await client.get(
            "/api/v1/auth/me",
            cookies={"session": session_id},
        )

    assert resp.status_code == 401
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Max-Age=0" in set_cookie

    events = [
        r
        for r in caplog.records
        if "auth.session.expired_cookie_cleared" in r.getMessage()
        or "malformed_payload" in r.getMessage()
    ]
    assert events, f"no expected log record in {caplog.text}"


async def test_malformed_cookie_clears_cookie(app_and_client, caplog):
    _app, client = app_and_client

    # 60 hex chars is not 64; middleware should treat it as malformed.
    with caplog.at_level(logging.INFO):
        resp = await client.get(
            "/api/v1/auth/me",
            cookies={"session": "a" * 60},
        )

    assert resp.status_code == 401
    set_cookie = resp.headers.get("set-cookie", "")
    assert "Max-Age=0" in set_cookie

    events = [
        r
        for r in caplog.records
        if "auth.session.expired_cookie_cleared" in r.getMessage()
        or "malformed_cookie" in r.getMessage()
    ]
    assert events, f"no expected log record in {caplog.text}"


async def test_middleware_runs_after_request_id(app_and_client):
    _app, client = app_and_client

    # A syntactically valid-looking but missing session id: the
    # middleware logs ``missing_key`` and clears the cookie; the
    # response carries an X-Request-ID from the outer middleware.
    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"session": "f" * 64},
    )
    assert resp.status_code == 401
    rid = resp.headers.get("x-request-id")
    assert rid and len(rid) >= 8


async def test_no_db_hit_on_missing_cookie(app_and_client):
    """Calling /healthz while no cookie is set does not trigger a DB query."""

    app, client = app_and_client

    engine = app.state.engine
    counts = {"checkouts": 0}

    from sqlalchemy import event

    def _on_checkout(*_args, **_kwargs):
        counts["checkouts"] += 1

    event.listen(engine.sync_engine, "checkout", _on_checkout)
    try:
        resp = await client.get("/healthz")
    finally:
        event.remove(engine.sync_engine, "checkout", _on_checkout)

    assert resp.status_code == 200
    assert counts["checkouts"] == 0


# Silence unused-import warnings in CI tools that scan strictly.
_ = json
