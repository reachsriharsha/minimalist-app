"""Tests for the ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE`` affordance.

The fixture lives entirely inside ``POST /auth/otp/request`` -- verify
has no branching, the middleware has no branching, the logging layer
has no branching. This test file pins that contract.

Includes a repo-hygiene check (case 9): no source file under
``backend/app/`` references ``test_otp_`` outside the three documented
call sites (``settings.py`` field definitions, ``router.py`` request
handler branch, ``email/factory.py`` startup guard).
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth import otp, otp_store
from app.auth.email import EmailProviderConfigError
from app.main import create_app
from app.settings import Settings


_TEST_EMAIL = "fixture@x.com"
_TEST_CODE = "246810"


@dataclass
class _LoggingSpy:
    """Captures log events plus also records send_otp calls."""

    calls: list[tuple[str, str]]

    async def send_otp(self, *, to: str, code: str) -> None:
        # Same as ConsoleEmailSender: emit the structured log event
        # so case 6 can observe the "decoy" code.
        from app.logging import get_logger

        self.calls.append((to, code))
        get_logger("app.auth.email.console").info(
            "auth.email.console_otp_sent",
            email_hash=otp.email_hash(to),
            code=code,
        )


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
        spy = _LoggingSpy(calls=[])
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


async def test_fixture_active_overwrites_stored_hash(build_client):
    app, client, _spy = await build_client(_settings())

    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    assert r.status_code == 204

    record = await otp_store.load_otp(_TEST_EMAIL, redis=app.state.redis)
    assert record is not None
    assert otp.verify_code(_TEST_CODE, record.code_hash) is True


async def test_fixture_inactive_for_non_matching_email(build_client):
    app, client, _spy = await build_client(_settings())

    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": "other@x.com"}
    )
    assert r.status_code == 204

    record = await otp_store.load_otp("other@x.com", redis=app.state.redis)
    assert record is not None
    # The real generated code is random, but not our test code.
    assert otp.verify_code(_TEST_CODE, record.code_hash) is False


async def test_fixture_off_in_env_test_when_code_empty(build_client):
    # Only email set; code is empty -> fixture is a no-op.
    app, client, _spy = await build_client(
        _settings(test_otp_code="")
    )

    r = await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    assert r.status_code == 204

    record = await otp_store.load_otp(_TEST_EMAIL, redis=app.state.redis)
    assert record is not None
    assert otp.verify_code(_TEST_CODE, record.code_hash) is False


async def test_fixture_refuses_to_boot_in_dev():
    settings = Settings(
        env="dev",
        test_otp_email=_TEST_EMAIL,
        test_otp_code=_TEST_CODE,
    )
    app = create_app(settings)

    with pytest.raises(EmailProviderConfigError):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover


async def test_fixture_does_not_bypass_rate_limit(build_client):
    _app, client, _spy = await build_client(
        _settings(otp_rate_per_minute=1, otp_rate_per_hour=10)
    )

    r1 = await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    r2 = await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    assert r1.status_code == 204
    assert r2.status_code == 429


async def test_console_logs_decoy_code_not_fixture_code(build_client):
    """With the fixture active, the console log shows the GENERATED code.

    The decoy exists so a human tailing backend logs cannot shortcut
    their way into the test account by eyeballing the log line -- they
    would have to know the configured ``TEST_OTP_CODE`` out of band.
    """

    _app, client, _spy = await build_client(_settings())

    with structlog.testing.capture_logs() as records:
        r = await client.post(
            "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
        )
    assert r.status_code == 204

    console_events = [
        r for r in records if r.get("event") == "auth.email.console_otp_sent"
    ]
    assert len(console_events) == 1
    code_in_log = console_events[0]["code"]
    # The test code is a specific known value; the decoy should differ
    # with overwhelming probability (there are 10**6 possible codes).
    assert code_in_log != _TEST_CODE


async def test_verify_matches_fixture_code(build_client):
    _app, client, _spy = await build_client(_settings())

    await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": _TEST_CODE},
    )
    assert r.status_code == 200


async def test_verify_generated_code_does_not_succeed(build_client):
    _app, client, spy = await build_client(_settings())

    await client.post(
        "/api/v1/auth/otp/request", json={"email": _TEST_EMAIL}
    )
    # Pull the generated code out of the spy and try to verify with it.
    assert spy.calls, "spy did not record any sends"
    _to, generated = spy.calls[0]

    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": _TEST_EMAIL, "code": generated},
    )
    # Generated code does NOT match -- the stored hash was overwritten
    # with a hash of the fixture code.
    assert r.status_code == 400


def test_grep_hygiene_test_otp_only_in_three_locations():
    """Only three source files under ``backend/app`` reference ``test_otp_``.

    Prevents a future contributor from sneaking a fourth use into
    production code. ``test_otp_email`` and ``test_otp_code`` are
    counted; matches inside docstrings/comments are deliberately
    included (we want exactly three *source files*).
    """

    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    assert app_root.is_dir(), app_root

    matches: set[str] = set()
    for path in app_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        if "test_otp_" in content:
            matches.add(path.relative_to(app_root).as_posix())

    # Exactly the three documented touch-points.
    expected = {
        "settings.py",
        "auth/router.py",
        "auth/email/factory.py",
    }
    assert matches == expected, matches


# ``ast`` is imported in case a future reviewer wants to tighten the
# hygiene check from a text match to a symbol match. Kept here so
# future evolution is one-edit, not one-discovery-of-stdlib.
_ = ast
