"""Smoke tests for the liveness, readiness, and request-id plumbing."""

from __future__ import annotations

import re

import pytest


async def test_healthz_returns_ok(client):
    """A1.1: /healthz returns 200 and carries X-Request-ID."""

    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    rid = resp.headers.get("x-request-id")
    assert rid and len(rid) >= 8


async def test_request_id_echoed_when_supplied(client):
    """A1.4: an incoming X-Request-ID is echoed verbatim."""

    resp = await client.get(
        "/healthz", headers={"X-Request-ID": "test-abc-123"}
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id") == "test-abc-123"


async def test_request_id_generated_when_absent(client):
    """A1.5: a missing X-Request-ID is generated as a non-trivial string."""

    resp = await client.get("/healthz")
    rid = resp.headers.get("x-request-id")
    assert rid is not None
    # UUID4 form preferred but we accept any non-trivial token.
    assert len(rid) >= 8
    # Should look roughly UUID-shaped by default.
    assert re.match(r"[0-9a-fA-F-]{8,}", rid)


async def test_readyz_reports_checks(client):
    """A1.2 / A2.2 / A2.3: /readyz returns the documented shape in all cases."""

    resp = await client.get("/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert set(body.keys()) == {"status", "checks"}
    assert body["status"] in ("ready", "not_ready")
    assert set(body["checks"].keys()) == {"db", "redis"}
    # Invariant: 200 iff both deps report "ok".
    if resp.status_code == 200:
        assert body["status"] == "ready"
        assert body["checks"]["db"] == "ok"
        assert body["checks"]["redis"] == "ok"
    else:
        assert body["status"] == "not_ready"
        assert (
            body["checks"]["db"] != "ok"
            or body["checks"]["redis"] != "ok"
        )


async def test_readyz_when_db_down(reset_env):
    """A2.2: unreachable DB -> 503 with non-ok checks.db."""

    # Force an obviously-unreachable DB URL; Redis is left at its default.
    settings = reset_env(
        DATABASE_URL="postgresql+asyncpg://nope:nope@127.0.0.1:1/none",
    )

    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            resp = await c.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["db"] != "ok"
    # Redis may or may not be up on the developer's box; we only assert that
    # the failing dependency is the one we broke.


async def test_readyz_when_redis_down(reset_env):
    """A2.3: unreachable Redis -> 503 with non-ok checks.redis."""

    settings = reset_env(
        REDIS_URL="redis://127.0.0.1:1/0",
    )

    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            resp = await c.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] != "ok"


async def test_unknown_route_returns_404_in_envelope(client):
    """A2.1: unknown routes use the error envelope with request_id."""

    resp = await client.get("/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "http_error"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["request_id"]
    # Request ID in body matches response header.
    assert body["error"]["request_id"] == resp.headers.get("x-request-id")


async def test_unhandled_exception_returns_envelope(settings):
    """A2.4: unhandled exceptions return the internal_error envelope and log."""

    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app(settings)

    @app.get("/__boom__")
    async def boom():  # pragma: no cover - behavior verified via response
        raise RuntimeError("boom")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            resp = await c.get("/__boom__")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal Server Error"
    assert body["error"]["request_id"] == resp.headers.get("x-request-id")
    # Security: tracebacks must never reach the client.
    raw = resp.text
    assert "Traceback" not in raw
    assert 'File "' not in raw
