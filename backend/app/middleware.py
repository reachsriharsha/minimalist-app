"""ASGI middleware: request ID correlation and unhandled-exception envelope."""

from __future__ import annotations

import json
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestIDMiddleware:
    """Pure ASGI middleware that assigns and surfaces a request ID.

    - Reads ``header_name`` from the incoming request. If present and
      non-empty, the value is echoed verbatim. Otherwise a UUID4 is minted.
    - Binds the request ID into :mod:`structlog` contextvars so every log
      line emitted during the request includes ``request_id``.
    - Writes the same ID onto the response in the ``http.response.start``
      message before the response headers are sent.

    A plain ASGI middleware is used instead of ``BaseHTTPMiddleware`` to avoid
    that class's known issues around streaming responses and background tasks.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        incoming = headers.get(self.header_name)
        request_id = incoming if incoming else str(uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)

        header_key = self.header_name.lower().encode("latin-1")
        header_value = request_id.encode("latin-1")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers") or [])
                # Drop any pre-existing value for our header so we control it.
                raw_headers = [
                    (k, v) for (k, v) in raw_headers if k.lower() != header_key
                ]
                raw_headers.append((header_key, header_value))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


class ExceptionEnvelopeMiddleware:
    """Convert unhandled exceptions into the documented error envelope.

    FastAPI routes ``HTTPException`` and ``RequestValidationError`` through
    Starlette's ``ExceptionMiddleware`` (which is *inside* ``ServerErrorMiddleware``
    and therefore inside our user-added middleware). Generic ``Exception``
    handlers, however, are wired onto ``ServerErrorMiddleware`` — which sits
    *outside* our middleware and bypasses our response headers. To surface the
    ``X-Request-ID`` header and the envelope shape uniformly for 500s, we
    catch unhandled exceptions here instead.

    Placement: mount this middleware **inside** :class:`RequestIDMiddleware`
    so the request ID is already bound into structlog contextvars when we
    log and emit the envelope.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except StarletteHTTPException:
            # HTTPException flows through ExceptionMiddleware (inner). If we
            # somehow see one here, re-raise to preserve existing semantics.
            raise
        except Exception as exc:  # noqa: BLE001
            if response_started:
                # Cannot rewrite headers after bytes are on the wire; let it
                # bubble up so the ASGI server can close the connection.
                raise

            # Deferred import to avoid a circular dependency with app.logging.
            from app.logging import get_logger

            ctx = structlog.contextvars.get_contextvars()
            request_id = str(ctx.get("request_id", ""))

            get_logger(__name__).error(
                "unhandled_exception",
                path=scope.get("path", ""),
                method=scope.get("method", ""),
                exc_info=exc,
            )

            body = json.dumps(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Internal Server Error",
                        "request_id": request_id,
                    }
                }
            ).encode("utf-8")

            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (
                            b"content-length",
                            str(len(body)).encode("latin-1"),
                        ),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": body,
                    "more_body": False,
                }
            )


__all__ = ["RequestIDMiddleware", "ExceptionEnvelopeMiddleware"]
