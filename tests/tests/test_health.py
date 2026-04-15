"""Black-box checks for ``/healthz`` and ``/readyz``."""

from __future__ import annotations

import httpx


def test_healthz_returns_ok(client: httpx.Client) -> None:
    """``GET /healthz`` is a liveness probe; it should be 200 + ``status=ok``."""

    response = client.get("/healthz")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"status": "ok"}


def test_readyz_reports_db_and_redis_ok(client: httpx.Client) -> None:
    """``GET /readyz`` must prove both Postgres and Redis are reachable."""

    response = client.get("/readyz")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("status") == "ready", body
    checks = body.get("checks")
    assert isinstance(checks, dict), body
    assert checks.get("db") == "ok", checks
    assert checks.get("redis") == "ok", checks
