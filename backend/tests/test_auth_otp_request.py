"""Endpoint tests for ``POST /api/v1/auth/otp/request``.

Uses a real Postgres + Redis via ``require_db`` / ``require_redis`` so
the happy path exercises the full rate-limit + store pipeline. The
email sender is monkeypatched onto ``app.state.email_sender`` to a
recording spy so send failures can be simulated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth import otp, otp_store
from app.auth.email import EmailSendError, ResendEmailSender
from app.main import create_app
from app.settings import Settings


@dataclass
class _SpySender:
    """Records every ``send_otp`` call; optionally raises."""

    raise_: Exception | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def send_otp(self, *, to: str, code: str) -> None:
        self.calls.append((to, code))
        if self.raise_ is not None:
            raise self.raise_


def _mock_transport(responder):
    def _handler(request):
        return responder(request)

    return httpx.MockTransport(_handler)


def _settings(**overrides) -> Settings:
    defaults: dict = dict(
        env="test",
        otp_rate_per_minute=1,
        otp_rate_per_hour=10,
        otp_code_ttl_seconds=600,
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
    """Factory that builds an app+client for a given Settings.

    Replaces ``app.state.email_sender`` with the supplied spy (or a
    fresh one) so tests can inspect send calls and simulate failures.
    """

    opened: list = []

    async def _open(settings: Settings, spy: _SpySender | None = None):
        app = create_app(settings)
        cm = app.router.lifespan_context(app)
        await cm.__aenter__()
        await app.state.redis.flushdb()
        if spy is None:
            spy = _SpySender()
        app.state.email_sender = spy
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        await client.__aenter__()
        opened.append((app, cm, client))
        return app, client, spy

    yield _open

    for app, cm, client in opened:
        try:
            await client.__aexit__(None, None, None)
        finally:
            await cm.__aexit__(None, None, None)


async def test_happy_path_console(build_client):
    app, client, spy = await build_client(_settings())

    resp = await client.post(
        "/api/v1/auth/otp/request", json={"email": "alice@x.com"}
    )
    assert resp.status_code == 204, resp.text

    assert len(spy.calls) == 1
    to, code = spy.calls[0]
    assert to == "alice@x.com"
    assert len(code) == 6 and code.isdigit()

    redis = app.state.redis
    record = await otp_store.load_otp("alice@x.com", redis=redis)
    assert record is not None
    assert record.attempts == 0
    ttl = await redis.ttl(otp.otp_key("alice@x.com"))
    assert 595 <= ttl <= 600


async def test_unknown_email_same_response(build_client):
    app, client, spy = await build_client(_settings())

    resp = await client.post(
        "/api/v1/auth/otp/request",
        json={"email": "never-registered@x.com"},
    )
    assert resp.status_code == 204
    assert len(spy.calls) == 1

    redis = app.state.redis
    assert (
        await otp_store.load_otp("never-registered@x.com", redis=redis)
        is not None
    )


async def test_rate_limit_minute_window(build_client):
    app, client, spy = await build_client(_settings())

    r1 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "b@x.com"}
    )
    r2 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "b@x.com"}
    )
    assert r1.status_code == 204
    assert r2.status_code == 429

    body = r2.json()
    assert body["detail"] == "too_many_requests"
    assert isinstance(body["retry_after"], int)
    assert 1 <= body["retry_after"] <= 60
    assert r2.headers["retry-after"] == str(body["retry_after"])


async def test_rate_limit_hour_window(build_client):
    app, client, spy = await build_client(
        _settings(otp_rate_per_minute=99, otp_rate_per_hour=3)
    )

    for _ in range(3):
        r = await client.post(
            "/api/v1/auth/otp/request", json={"email": "c@x.com"}
        )
        assert r.status_code == 204

    r4 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "c@x.com"}
    )
    assert r4.status_code == 429
    # Hour-window retry_after range.
    assert 1 <= r4.json()["retry_after"] <= 3600


async def test_email_shape_validation(build_client):
    _app, client, _ = await build_client(_settings())

    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": "not-an-email"}
    )
    # Either 400 or 422 depending on where validation lives; both are
    # acceptable per the test spec. Asserting "not a 5xx" keeps the
    # behavior pinned without over-specifying.
    assert 400 <= r.status_code < 500


async def test_extra_field_is_rejected(build_client):
    _app, client, _ = await build_client(_settings())
    r = await client.post(
        "/api/v1/auth/otp/request",
        json={"email": "d@x.com", "foo": "bar"},
    )
    assert r.status_code == 422


async def test_resend_500_still_returns_204(build_client):
    # Use a Resend sender with a MockTransport that returns 500.
    def _err(_request):
        return httpx.Response(500, json={"message": "oops"})

    http_client = httpx.AsyncClient(transport=_mock_transport(_err))
    resend = ResendEmailSender(
        api_key="k", from_="f", timeout=5.0, http_client=http_client
    )

    app, client, _ = await build_client(
        _settings(email_provider="resend", resend_api_key="k"),
        spy=resend,  # type: ignore[arg-type]
    )
    try:
        r = await client.post(
            "/api/v1/auth/otp/request", json={"email": "e@x.com"}
        )
        assert r.status_code == 204

        record = await otp_store.load_otp(
            "e@x.com", redis=app.state.redis
        )
        assert record is not None
    finally:
        await http_client.aclose()


async def test_resend_timeout_still_returns_204(build_client):
    def _timeout(_request):
        raise httpx.ReadTimeout("slow")

    http_client = httpx.AsyncClient(transport=_mock_transport(_timeout))
    resend = ResendEmailSender(
        api_key="k", from_="f", timeout=0.1, http_client=http_client
    )

    app, client, _ = await build_client(
        _settings(email_provider="resend", resend_api_key="k"),
        spy=resend,  # type: ignore[arg-type]
    )
    try:
        r = await client.post(
            "/api/v1/auth/otp/request", json={"email": "f@x.com"}
        )
        assert r.status_code == 204
    finally:
        await http_client.aclose()


async def test_case_insensitive_email_key(build_client):
    app, client, _ = await build_client(_settings())

    r1 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "Alice@X.com"}
    )
    assert r1.status_code == 204

    # Second request with different casing should hit the same rate-
    # limit bucket (both normalize to the same email_hash).
    r2 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "alice@x.com"}
    )
    assert r2.status_code == 429


async def test_send_failed_keeps_stored_otp(build_client):
    """When email send raises, the stored OTP record stays intact.

    Enables a retry of ``/otp/verify`` within TTL without re-requesting.
    """

    spy = _SpySender(raise_=EmailSendError(status_code=500, detail="oops"))
    app, client, _ = await build_client(_settings(), spy=spy)

    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": "g@x.com"}
    )
    assert r.status_code == 204

    record = await otp_store.load_otp("g@x.com", redis=app.state.redis)
    assert record is not None


async def test_response_body_is_empty_on_204(build_client):
    _app, client, _ = await build_client(_settings())
    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": "h@x.com"}
    )
    assert r.status_code == 204
    assert r.content == b""
