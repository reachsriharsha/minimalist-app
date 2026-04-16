"""ASGI middleware: request ID correlation, session resolution, and
unhandled-exception envelope."""

from __future__ import annotations

import hashlib
import json
import re
from http.cookies import SimpleCookie
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


# ---------------------------------------------------------------------------
# Session middleware (feat_auth_001)
# ---------------------------------------------------------------------------
#
# Installed between ``RequestIDMiddleware`` (outermost, binds request_id) and
# ``ExceptionEnvelopeMiddleware`` so:
#
# 1. Log events emitted from the middleware carry ``request_id``.
# 2. Any ``HTTPException`` raised by a downstream dependency (401, 403)
#    flows through the envelope handler unchanged.
#
# On every request:
#
# - Reads ``settings.session_cookie_name`` from the request cookies.
# - If present, makes a single ``GET session:<id>`` to Redis.
# - On hit: populates ``request.state.auth`` with an :class:`AuthContext`.
# - On miss, malformed payload, or malformed cookie: ``request.state.auth``
#   is ``None`` and the response carries a ``Set-Cookie`` that clears the
#   cookie (``Max-Age=0``).
#
# The middleware NEVER touches the database. Role data lives in the session
# payload; see §2 of ``docs/design/auth-login-and-roles.md``.

_SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _session_id_hash(session_id: str) -> str:
    """Return a short, non-reversible tag for a session ID.

    Used in the one log event this middleware emits so operators can
    correlate ``expired_cookie_cleared`` lines without the log stream
    ever containing a raw, re-usable session ID.
    """

    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


class SessionMiddleware:
    """Resolve the session cookie to an :class:`AuthContext`.

    Pure ASGI middleware (same style as :class:`RequestIDMiddleware`) to
    avoid ``BaseHTTPMiddleware``'s streaming-response pitfalls.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Deferred imports so test code that overrides settings via
        # ``dependency_overrides`` or env mutations still picks up fresh
        # values on each app build.
        from app.auth import sessions
        from app.auth.schemas import AuthContext
        from app.logging import get_logger
        from app.settings import Settings

        log = get_logger(__name__)

        settings: Settings | None = None
        redis = None
        # The app is always available on the scope in Starlette/FastAPI.
        app_obj = scope.get("app")
        if app_obj is not None:
            settings = getattr(app_obj.state, "settings", None)
            redis = getattr(app_obj.state, "redis", None)

        # Defensive fallback: if the app hasn't been fully bootstrapped
        # yet (test builds that skip lifespan, unusual ordering), behave
        # like the anonymous path so we never raise from middleware.
        cookie_name = (
            settings.session_cookie_name
            if settings is not None
            else "session"
        )

        # Pull the cookie value out of the headers without constructing
        # a full Starlette ``Request`` (cheaper; avoids early body reads).
        raw_cookie_header = _read_header(scope, b"cookie")
        cookie_value: str | None = None
        if raw_cookie_header:
            try:
                jar = SimpleCookie()
                jar.load(raw_cookie_header)
                morsel = jar.get(cookie_name)
                if morsel is not None:
                    cookie_value = morsel.value
            except Exception:  # noqa: BLE001 - defensive
                cookie_value = None

        ctx: AuthContext | None = None
        clear_cookie_reason: str | None = None

        if cookie_value is not None and redis is not None:
            if not _SESSION_ID_PATTERN.match(cookie_value):
                # Cookie was present but obviously not one we minted
                # (wrong length, non-hex). Clear and log.
                clear_cookie_reason = "malformed_cookie"
            else:
                # One Redis GET. sessions.get already collapses
                # "missing key" and "malformed payload" to None, but we
                # want to distinguish them for the log line, so probe
                # the raw value first.
                raw = await redis.get(f"session:{cookie_value}")
                if raw is None:
                    clear_cookie_reason = "missing_key"
                else:
                    ctx = await sessions.get(cookie_value, redis=redis)
                    if ctx is None:
                        clear_cookie_reason = "malformed_payload"

        # Stash the result so downstream dependencies can read it.
        # Starlette copies ``scope["state"]`` onto ``request.state`` for
        # each request, so this is visible as ``request.state.auth``.
        state = scope.setdefault("state", {})
        state["auth"] = ctx

        if clear_cookie_reason is not None and cookie_value is not None:
            log.info(
                "auth.session.expired_cookie_cleared",
                reason=clear_cookie_reason,
                session_id_hash=_session_id_hash(cookie_value),
            )

        if clear_cookie_reason is None:
            await self.app(scope, receive, send)
            return

        # Need to rewrite response headers to append a Set-Cookie that
        # clears the bad cookie. ``secure`` flag is echoed from settings
        # so staging/prod clears are also marked Secure.
        secure = (
            settings.session_cookie_secure if settings is not None else False
        )
        clear_cookie_header = _build_clear_cookie_header(cookie_name, secure)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", clear_cookie_header))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _read_header(scope: Scope, name: bytes) -> str | None:
    """Return the first value for ``name`` (lower-case, bytes) or ``None``."""

    for k, v in scope.get("headers", []) or []:
        if k == name:
            try:
                return v.decode("latin-1")
            except Exception:  # noqa: BLE001 - defensive
                return None
    return None


def _build_clear_cookie_header(name: str, secure: bool) -> bytes:
    """Build a ``Set-Cookie`` value that clears ``name``.

    Attributes match the mint path so the browser treats the clear
    as a scope-identical overwrite: ``Path=/``, ``HttpOnly``,
    ``SameSite=Lax``, plus ``Secure`` when configured.
    """

    parts = [
        f"{name}=",
        "Max-Age=0",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts).encode("latin-1")


__all__ = [
    "RequestIDMiddleware",
    "ExceptionEnvelopeMiddleware",
    "SessionMiddleware",
]
