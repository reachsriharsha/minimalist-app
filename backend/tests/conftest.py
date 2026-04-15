"""Test fixtures for the in-container backend smoke suite.

This suite is a **developer-loop** convenience, not the template's external
contract. The external contract lives with ``feat_testing_001``. Tests here
should stay small and focused; if a test needs live Postgres or Redis, guard
it with :func:`require_db` / :func:`require_redis` so running ``uv run pytest``
on a bare checkout still exits 0.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings, reset_settings_cache


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async fixtures.

    ``pytest-asyncio`` creates per-test loops by default; a session loop makes
    the ``client`` fixture reusable without tearing down the ASGI app on every
    test.
    """

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture
def settings() -> Settings:
    """Per-test :class:`Settings` instance.

    Clears the ``get_settings`` LRU cache so env-var changes made during a
    test are respected.
    """

    reset_settings_cache()
    return Settings()


@pytest_asyncio.fixture
async def app(settings: Settings):
    """Build a fresh app for each test, running its lifespan explicitly."""

    instance = create_app(settings)
    # Enter the lifespan so app.state is populated.
    async with instance.router.lifespan_context(instance):
        yield instance


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Dependency guards
# ---------------------------------------------------------------------------


async def _postgres_reachable(url: str) -> tuple[bool, str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


async def _redis_reachable(url: str) -> tuple[bool, str]:
    from redis.asyncio import from_url

    client = from_url(url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


@pytest_asyncio.fixture
async def require_db(settings: Settings) -> str:
    """Skip the test if Postgres at ``settings.database_url`` is unreachable."""

    ok, err = await _postgres_reachable(settings.database_url)
    if not ok:
        pytest.skip(
            f"postgres not reachable at {settings.database_url}: {err}"
        )
    return settings.database_url


@pytest_asyncio.fixture
async def require_redis(settings: Settings) -> str:
    """Skip the test if Redis at ``settings.redis_url`` is unreachable."""

    ok, err = await _redis_reachable(settings.redis_url)
    if not ok:
        pytest.skip(f"redis not reachable at {settings.redis_url}: {err}")
    return settings.redis_url


# ---------------------------------------------------------------------------
# Env var helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_env(monkeypatch):
    """Helper that lets a test override env vars and get a fresh Settings."""

    def _set(**overrides: str):
        for k, v in overrides.items():
            monkeypatch.setenv(k.upper(), v)
        reset_settings_cache()
        return Settings()

    yield _set
    reset_settings_cache()


# Ensure a predictable baseline: we do not want the developer's real .env to
# sneak pytest runs into touching their local DB. Tests that need real deps
# use ``require_db`` / ``require_redis`` which probe the configured URL
# explicitly.
@pytest.fixture(autouse=True)
def _quiet_defaults(monkeypatch):
    # Only set values the test did not already override via its own monkeypatch.
    monkeypatch.setenv("LOG_LEVEL", os.environ.get("LOG_LEVEL", "WARNING"))
    yield
