"""Global exception handlers producing the documented error envelope."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger
from app.schemas import ErrorBody, ErrorEnvelope
from app.settings import get_settings

_log = get_logger(__name__)


def _request_id(request: Request) -> str:
    """Resolve the current request ID.

    Prefers the value bound into :mod:`structlog` contextvars by
    :class:`app.middleware.RequestIDMiddleware` (set for *every* request,
    whether or not the client sent a header). Falls back to the incoming
    request header for safety.
    """

    ctx = structlog.contextvars.get_contextvars()
    rid = ctx.get("request_id")
    if rid:
        return str(rid)
    header = get_settings().request_id_header
    return request.headers.get(header, "")


def _envelope(code: str, message: str, request_id: str) -> dict[str, Any]:
    return ErrorEnvelope(
        error=ErrorBody(code=code, message=message, request_id=request_id)
    ).model_dump()


def install_exception_handlers(app: FastAPI) -> None:
    """Attach handlers for HTTP, validation, and unhandled exceptions."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        rid = _request_id(request)
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.detail
            else "HTTP error"
        )
        _log.info(
            "http_error",
            status_code=exc.status_code,
            path=request.url.path,
            detail=exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("http_error", str(message), rid),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        rid = _request_id(request)
        _log.info(
            "validation_error",
            path=request.url.path,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "validation_error",
                "Request validation failed.",
                rid,
            ),
        )

    # Note: bare ``Exception`` handlers are intentionally *not* registered on
    # the FastAPI app. FastAPI wires them into Starlette's
    # ``ServerErrorMiddleware``, which sits *outside* our user middleware and
    # emits its response bypassing :class:`app.middleware.RequestIDMiddleware`.
    # Uniform 500 envelopes (with ``X-Request-ID``) are produced by
    # :class:`app.middleware.ExceptionEnvelopeMiddleware` instead.


__all__ = ["install_exception_handlers"]
