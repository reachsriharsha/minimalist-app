"""Verify the test-only mint endpoint is mounted only when ``env == "test"``.

The real ``/auth/me`` is mounted in every environment; the env gate only
applies to the mint. All four cases in ``test_auth_001.md`` →
``test_auth_test_mint_gating.py`` are covered.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings, reset_settings_cache


async def _probe(settings: Settings, path: str, method: str = "GET", **kw):
    reset_settings_cache()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            if method == "GET":
                return await c.get(path, **kw)
            return await c.post(path, **kw)


@pytest.mark.parametrize("env", ["dev", "prod"])
async def test_test_mint_not_mounted_outside_test(env):
    resp = await _probe(
        Settings(env=env),
        "/api/v1/_test/session",
        method="POST",
        json={"email": "a@x.com"},
    )
    assert resp.status_code == 404


async def test_test_mint_mounted_in_test(require_db, require_redis):
    # Clean slate first: flush redis + truncate users to avoid collisions
    # from other tests in this module.
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

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

    resp = await _probe(
        Settings(env="test"),
        "/api/v1/_test/session",
        method="POST",
        json={"email": "a@x.com", "display_name": "Alice"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
async def test_auth_me_mounted_in_every_env(env):
    resp = await _probe(Settings(env=env), "/api/v1/auth/me")
    assert resp.status_code == 401
