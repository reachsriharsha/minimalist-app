"""Integration tests for :class:`app.middleware.SessionMiddleware`.

Exercises the middleware behaviour end-to-end through ``httpx.AsyncClient``:

- No cookie → request goes through with ``request.state.auth = None``.
- Valid cookie → ``request.state.auth`` is populated from the Redis payload.
- Expired / malformed session → 401 from the dependency, ``Set-Cookie``
  clears the cookie, a log event is emitted.
- ``RequestIDMiddleware`` remains outermost (log event carries ``request_id``).
"""

from __future__ import annotations

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings, reset_settings_cache


@pytest.fixture
def test_settings(require_db, require_redis) -> Settings:
    """Settings pinned to ``env=test`` so the mint endpoint is mounted."""

    reset_settings_cache()
    return Settings(env="test")


@pytest.fixture
async def app_and_client(test_settings):
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
    # No Set-Cookie at all — public endpoint, no session work happened.
    assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}


async def _mint(client: AsyncClient, email: str) -> str:
    """Mint via the test-only endpoint and return the ``session`` cookie."""

    resp = await client.post(
        "/api/v1/_test/session",
        json={"email": email, "display_name": "Tester"},
    )
    assert resp.status_code == 200, resp.text
    set_cookie = resp.headers.get("set-cookie")
    assert set_cookie, "test mint did not set a cookie"
    # Extract the ``session=<id>`` value from the header.
    value = set_cookie.split(";", 1)[0]
    assert "=" in value
    name, raw = value.split("=", 1)
    assert name.strip() == "session"
    return raw


async def test_valid_cookie_populates_context(app_and_client):
    _app, client = app_and_client

    session_id = await _mint(client, "a@x.com")

    # Now call /auth/me carrying the cookie and verify the payload the
    # middleware's context produced.
    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"session": session_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "a@x.com"
    assert "user" in body["roles"]


async def test_expired_session_clears_cookie(app_and_client):
    app, client = app_and_client
    redis = app.state.redis

    session_id = await _mint(client, "b@x.com")

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

    session_id = await _mint(client, "c@x.com")

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

    # Log line should say ``reason=malformed_payload``. The structured
    # logger renders JSON records on stdout; ``caplog`` captures the raw
    # ``LogRecord.getMessage`` which is the positional event name in our
    # wiring.
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

    # Just confirm that a request that hits our middleware path still
    # carries the X-Request-ID header, proving RequestIDMiddleware is
    # still outermost.
    resp = await client.get(
        "/api/v1/auth/me",
        cookies={"session": "f" * 64},  # malformed-length? no, length OK
    )
    # With a syntactically valid-looking but missing session:
    # the middleware logs ``missing_key`` and clears the cookie; the
    # response carries an X-Request-ID from the outer middleware.
    assert resp.status_code == 401
    rid = resp.headers.get("x-request-id")
    assert rid and len(rid) >= 8


async def test_no_db_hit_on_missing_cookie(app_and_client):
    """Calling /healthz while no cookie is set does not trigger a DB query.

    This is a weak proxy for the middleware's "no DB hit per request"
    invariant — in practice middleware runs on every request, and we
    want it to stay out of the data layer. A stronger check would wire
    a SQLAlchemy event listener; for now we rely on the fact that a
    successful /healthz only ever touches app.state.
    """

    app, client = app_and_client

    # Use the engine's pool-reset event to count connection checkouts.
    # If the middleware touched the DB, we would see a checkout count
    # after the probe.
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
