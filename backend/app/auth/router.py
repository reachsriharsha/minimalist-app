"""HTTP routes for the ``auth`` domain.

Mounted under ``/api/v1/auth`` by :mod:`app.api.v1`.

Routes:

- ``GET /me`` -- returns the authenticated principal (feat_auth_001).
- ``POST /logout`` -- deletes the current session and clears the
  cookie (feat_auth_001).
- ``POST /otp/request`` -- sends an OTP code to the given email
  (feat_auth_002).
- ``POST /otp/verify`` -- verifies a code, mints a session, sets the
  cookie (feat_auth_002).

The env-gated ``POST /_test/session`` endpoint that feat_auth_001
shipped has been removed -- OTP verify is now the single session-
minting path.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import otp, otp_store, service, sessions
from app.auth.dependencies import current_user
from app.auth.email import EmailSender, EmailSendError, get_email_sender
from app.auth.models import User
from app.auth.schemas import (
    AuthContext,
    MeResponse,
    OtpRequestIn,
    OtpVerifyIn,
)
from app.db import get_session
from app.logging import get_logger
from app.redis_client import get_redis
from app.settings import Settings


def _settings(request: Request) -> Settings:
    """Pull the live :class:`Settings` off ``app.state``.

    ``create_app`` installs the exact :class:`Settings` instance the
    caller passed (or the env-derived default) onto ``app.state``; tests
    that build an app with a synthetic :class:`Settings` want *that*
    value flowing into every handler, not the lru-cached env default
    that ``app.settings.get_settings`` returns. See
    ``docs/specs/feat_auth_001/design_auth_001.md`` -> "Settings
    additions".
    """

    return request.app.state.settings


router = APIRouter(tags=["auth"])


# Lightweight adapter so :func:`app.auth.sessions.create` -- which reads
# ``user.id``, ``user.email``, and iterates ``user.roles``-with-``.name``
# -- works with the ``(user, role_names)`` tuple returned by the service
# layer, without triggering an async lazy-load on :attr:`User.roles`.
def _UserLike(*, id: int, email: str, role_names: list[str]):  # noqa: N802
    roles = [SimpleNamespace(name=n) for n in role_names]
    return SimpleNamespace(id=id, email=email, roles=roles)


# Uniform verify failure body. Same shape for missing key, expired
# record, wrong code, attempts exhausted, and shape-validation errors
# on ``{email, code}``. The structured log event carries the real
# reason; the wire body does not, per design-doc §7.1.
_VERIFY_FAIL_DETAIL = "invalid_or_expired_code"


def _session_id_hash(session_id: str) -> str:
    """Return a short, non-reversible tag for a session ID.

    Matches the 16-char SHA-256 truncation used by
    :class:`app.middleware.SessionMiddleware` so the two loggers
    produce correlatable hashes.
    """

    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


@router.get("/me", response_model=MeResponse)
async def me(
    ctx: AuthContext = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> MeResponse:
    """Return the authenticated user's profile.

    The session payload already carries ``user_id``, ``email``, and
    ``roles``; ``display_name`` is the only field that isn't in the
    payload today, so we load it from the database. We intentionally
    keep ``display_name`` *off* the session payload to keep that blob
    small and stable across profile edits.

    This DB read happens only on ``/me``, not on every request -- and
    fetching a single row by primary key is cheap. The zero-DB-hit
    invariant in the design doc is specifically about the middleware
    (and therefore every request-gated dependency), not about the
    ``/me`` endpoint, which is the place a caller explicitly asks for
    profile data.
    """

    user = await db.get(User, ctx.user_id)
    display_name = user.display_name if user is not None else None

    return MeResponse(
        user_id=ctx.user_id,
        email=ctx.email,
        display_name=display_name,
        roles=list(ctx.roles),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    ctx: AuthContext = Depends(current_user),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(_settings),
) -> Response:
    """Invalidate the current session and clear the cookie."""

    await sessions.delete(ctx.session_id, ctx.user_id, redis=redis)

    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# ---------------------------------------------------------------------------
# OTP endpoints (feat_auth_002)
# ---------------------------------------------------------------------------
#
# See ``docs/specs/feat_auth_002/design_auth_002.md`` for the two data-flow
# sequence diagrams. Security posture notes:
#
# - ``/otp/request`` never reads from Postgres. Same 204 for known and
#   unknown emails.
# - ``/otp/verify`` returns the *same* 400 body for missing/expired/
#   wrong/exhausted. The log event carries the distinguishing reason.
# - The test-OTP fixture (``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE``) is
#   the ONLY non-production code path in this module. Fixture gating
#   lives exclusively inside ``request_otp`` below (plus the startup
#   guard in ``email/factory.py``).


@router.post(
    "/otp/request",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        429: {
            "description": "Rate limit exceeded.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "too_many_requests",
                        "retry_after": 42,
                    }
                }
            },
        },
    },
)
async def request_otp(
    body: OtpRequestIn,
    response: Response,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Response:
    """Send an OTP code to ``body.email``.

    Returns ``204 No Content`` on success and on email-send failure
    (we still persist the OTP so a user whose provider bounces can
    retry verify once the provider recovers). Returns ``429`` with a
    ``Retry-After`` header when the per-email rate limit is exceeded.

    **Never** performs a database read or write. Account existence
    is resolved on verify, not request (design-doc §7.1 anti-
    enumeration rule).
    """

    log = get_logger(__name__)
    normalized = body.email.strip().lower()

    # ---- Rate limit ------------------------------------------------------
    rate = await otp_store.check_and_increment_rate(
        normalized,
        redis=redis,
        per_minute_limit=settings.otp_rate_per_minute,
        per_hour_limit=settings.otp_rate_per_hour,
    )
    if not rate.allowed:
        log.info(
            "auth.otp.rate_limited",
            email_hash=otp.email_hash(normalized),
            retry_after=rate.retry_after,
            window=rate.window,
        )
        # ``JSONResponse`` short-circuits the declared 204 status and
        # lets us attach the documented body + ``Retry-After`` header.
        # Uses the same ``detail`` key as FastAPI's default
        # ``HTTPException`` body so consumers need not special-case.
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "too_many_requests",
                "retry_after": rate.retry_after,
            },
            headers={"Retry-After": str(rate.retry_after)},
        )

    # ---- Mint + store ----------------------------------------------------
    code = otp.generate_code()
    code_hash = otp.hash_code(code)

    await otp_store.store_otp(
        normalized,
        code_hash,
        redis=redis,
        ttl_seconds=settings.otp_code_ttl_seconds,
    )

    # ---- Test-OTP fixture overwrite (the only non-prod branch) -----------
    # When ENV=test AND both test vars are non-empty AND the request
    # email matches the configured test email, overwrite the stored
    # hash with one derived from the configured test code. The real
    # generated ``code`` stays in flight (ConsoleEmailSender will log
    # it as a decoy) but verify will only succeed for the test code.
    if (
        settings.env == "test"
        and settings.test_otp_email
        and settings.test_otp_code
        and normalized == settings.test_otp_email.strip().lower()
    ):
        await otp_store.store_otp(
            normalized,
            otp.hash_code(settings.test_otp_code.strip()),
            redis=redis,
            ttl_seconds=settings.otp_code_ttl_seconds,
        )

    # ---- Deliver ---------------------------------------------------------
    provider_name = settings.email_provider
    try:
        await email_sender.send_otp(to=normalized, code=code)
    except EmailSendError as exc:
        reason = "timeout" if exc.status_code is None else "http_error"
        log.info(
            "auth.otp.send_failed",
            email_hash=otp.email_hash(normalized),
            provider=provider_name,
            reason=reason,
            http_status=exc.status_code,
        )
    except Exception as exc:  # noqa: BLE001 -- defensive
        # Any unexpected exception from a provider is logged and
        # swallowed so the response shape stays constant. The rate
        # limiter above already protects us from weaponization.
        log.info(
            "auth.otp.send_failed",
            email_hash=otp.email_hash(normalized),
            provider=provider_name,
            reason="unexpected",
            http_status=None,
            error=type(exc).__name__,
        )
    else:
        log.info(
            "auth.otp.requested",
            email_hash=otp.email_hash(normalized),
            provider=provider_name,
        )

    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/otp/verify",
    status_code=status.HTTP_200_OK,
    response_model=MeResponse,
    responses={
        400: {
            "description": "Invalid or expired OTP code.",
            "content": {
                "application/json": {
                    "example": {"detail": _VERIFY_FAIL_DETAIL}
                }
            },
        },
    },
)
async def verify_otp(
    request: Request,
    response: Response,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(_settings),
) -> MeResponse:
    """Verify an OTP and mint a session.

    All four bad-code conditions (missing record, expired, wrong,
    exhausted) return the **same body** ``{"detail": "invalid_or_expired_code"}``
    with HTTP 400. Shape-validation failures on the body (non-JSON,
    missing field, non-six-digit code, malformed email) also map to
    the same 400 -- we do not let a 422 leak because it would
    distinguish "shape wrong" from "wrong code".
    """

    log = get_logger(__name__)

    # ---- Parse + validate the body ourselves so we can map a Pydantic
    # ValidationError onto the uniform 400 instead of letting FastAPI
    # emit a 422. ``from_async`` helpers aren't needed -- we read the
    # whole body then build the model.
    try:
        raw_body = await request.json()
    except Exception:  # noqa: BLE001 -- malformed JSON
        raise HTTPException(
            status_code=400, detail=_VERIFY_FAIL_DETAIL
        )

    try:
        parsed = OtpVerifyIn.model_validate(raw_body)
    except ValidationError:
        raise HTTPException(
            status_code=400, detail=_VERIFY_FAIL_DETAIL
        )

    normalized = parsed.email.strip().lower()

    # ---- Load record -----------------------------------------------------
    record = await otp_store.load_otp(normalized, redis=redis)

    if record is None:
        log.info(
            "auth.otp.failed",
            email_hash=otp.email_hash(normalized),
            reason="missing",
            attempts=0,
        )
        raise HTTPException(
            status_code=400, detail=_VERIFY_FAIL_DETAIL
        )

    if record.attempts >= settings.otp_max_attempts:
        await otp_store.consume_otp(normalized, redis=redis)
        log.info(
            "auth.otp.failed",
            email_hash=otp.email_hash(normalized),
            reason="attempts_exhausted",
            attempts=record.attempts,
        )
        raise HTTPException(
            status_code=400, detail=_VERIFY_FAIL_DETAIL
        )

    if not otp.verify_code(parsed.code, record.code_hash):
        new_attempts = await otp_store.increment_attempts_preserve_ttl(
            normalized, redis=redis
        )
        log.info(
            "auth.otp.failed",
            email_hash=otp.email_hash(normalized),
            reason="wrong_code",
            attempts=new_attempts,
        )
        raise HTTPException(
            status_code=400, detail=_VERIFY_FAIL_DETAIL
        )

    # ---- Match: consume the OTP (one-shot) and build a session -----------
    await otp_store.consume_otp(normalized, redis=redis)

    user, role_names, new_user = await service.find_or_create_user_for_otp(
        db, email=normalized, settings=settings
    )

    # Deactivated-user row: not reachable in feat_auth_002 because
    # ``users.is_active`` does not exist yet (see design-doc
    # "Deviations"). The ``getattr`` keeps the behavior forward-
    # compatible: a later migration adding the column will make this
    # branch come online automatically.
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="account_disabled")

    session_id = await sessions.create(
        _UserLike(id=user.id, email=user.email, role_names=role_names),
        redis=redis,
        ttl_seconds=settings.session_ttl_seconds,
    )

    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )

    log.info(
        "auth.otp.verified",
        user_id=user.id,
        email_hash=otp.email_hash(normalized),
        new_user=new_user,
    )
    # Emitted alongside the verify event so operators have a single
    # hash to correlate the newly-issued session. Matches the
    # ``session_id_hash`` shape used by ``SessionMiddleware``.
    log.info(
        "auth.session.created",
        user_id=user.id,
        session_id_hash=_session_id_hash(session_id),
    )

    return MeResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=list(role_names),
    )


__all__ = ["router"]
