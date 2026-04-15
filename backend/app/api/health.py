"""Liveness and readiness endpoints mounted at the app root."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.logging import get_logger
from app.schemas import DependencyCheck, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])

_log = get_logger(__name__)


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness probe. Always returns 200 if the process is running."""

    return HealthResponse(status="ok")


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness probe. Reports per-dependency health without raising."""

    db_status = "ok"
    redis_status = "ok"

    # Database probe: open a short-lived session and run SELECT 1.
    try:
        sessionmaker = request.app.state.sessionmaker
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - deliberately broad
        db_status = f"{type(exc).__name__}: {exc}" or type(exc).__name__
        _log.warning("readiness_db_failed", error=str(exc))

    # Redis probe.
    try:
        redis = request.app.state.redis
        await redis.ping()
    except Exception as exc:  # noqa: BLE001 - deliberately broad
        redis_status = f"{type(exc).__name__}: {exc}" or type(exc).__name__
        _log.warning("readiness_redis_failed", error=str(exc))

    checks = DependencyCheck(db=db_status, redis=redis_status)
    ready = db_status == "ok" and redis_status == "ok"
    body = ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=checks,
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content=body.model_dump(),
    )


__all__ = ["router"]
