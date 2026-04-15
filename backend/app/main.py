"""FastAPI application factory and module-level ASGI instance.

Run with::

    uv run uvicorn app.main:app --reload

The module-level ``app`` is created at import time for ASGI servers; tests
that want isolated state should call :func:`create_app` directly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1 import api_v1_router
from app.db import build_engine, build_sessionmaker
from app.errors import install_exception_handlers
from app.logging import configure_logging, get_logger
from app.middleware import ExceptionEnvelopeMiddleware, RequestIDMiddleware
from app.redis_client import build_redis
from app.settings import Settings, get_settings


def _make_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log = get_logger(__name__)
        log.info(
            "app_startup",
            app_name=settings.app_name,
            env=settings.env,
        )

        # Build connection-holders. These are cheap and do not open sockets.
        engine = build_engine(settings.database_url)
        sessionmaker = build_sessionmaker(engine)
        redis = build_redis(settings.redis_url)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.redis = redis

        try:
            yield
        finally:
            log.info("app_shutdown")
            try:
                await redis.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("redis_close_failed", error=str(exc))
            try:
                await engine.dispose()
            except Exception as exc:  # noqa: BLE001
                log.warning("engine_dispose_failed", error=str(exc))

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct a fresh :class:`FastAPI` application.

    A dedicated factory keeps tests isolated: each ``create_app()`` call
    produces independent middleware stacks, routers, and ``app.state``.
    """

    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    app = FastAPI(
        title=resolved.app_name,
        version="0.1.0",
        lifespan=_make_lifespan(resolved),
    )

    # Middleware order (outermost-first after ServerErrorMiddleware):
    #   RequestIDMiddleware -> ExceptionEnvelopeMiddleware -> ExceptionMiddleware -> app
    # ``add_middleware`` prepends to the stack, so the LAST call is outermost.
    app.add_middleware(ExceptionEnvelopeMiddleware)
    app.add_middleware(
        RequestIDMiddleware, header_name=resolved.request_id_header
    )

    install_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_v1_router)

    return app


# Module-level ASGI app for ``uvicorn app.main:app``.
app = create_app()


__all__ = ["create_app", "app"]
