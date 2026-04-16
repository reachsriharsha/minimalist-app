"""HTTP routes for the ``auth`` domain.

Exposes two production routes mounted under ``/api/v1/auth``:

- ``GET /me`` — returns the authenticated principal.
- ``POST /logout`` — deletes the current session and clears the cookie.

And one env-gated route mounted under ``/api/v1/_test`` **only when**
``settings.env == "test"``:

- ``POST /session`` — mints a session for testing. Created in
  ``feat_auth_001`` so the middleware and ``/me`` + ``/logout`` pair can
  be exercised end-to-end before real login flows land. Will be removed
  by ``feat_auth_002`` when OTP verify becomes the real session minter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service, sessions
from app.auth.dependencies import current_user
from app.auth.models import User
from app.auth.schemas import AuthContext, MeResponse, TestSessionRequest
from app.db import get_session
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(tags=["auth"])


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

    This DB read happens only on ``/me``, not on every request — and
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
    settings: Settings = Depends(get_settings),
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
# Test-only mint endpoint (env-gated)
# ---------------------------------------------------------------------------
#
# Mounted by ``app/main.py`` only when ``settings.env == "test"``. Importing
# this symbol is safe in any environment — the route is registered on a
# separate ``APIRouter`` that ``main.py`` chooses to include or not.
#
# Removed entirely by ``feat_auth_002``.

test_router = APIRouter(prefix="/_test", tags=["_test"])


@test_router.post("/session", response_model=MeResponse, status_code=200)
async def mint_test_session(
    body: TestSessionRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    """Mint a session for the given email. ``env == "test"`` only.

    Find-or-create the user, apply ``ADMIN_EMAILS`` bootstrap, optionally
    grant extra roles, create a session, set the cookie, and return the
    same payload shape as ``GET /auth/me`` so tests can assert on the
    same schema in both places.
    """

    user = await service.find_or_create_user_for_test(
        db,
        email=body.email,
        display_name=body.display_name,
        extra_roles=body.roles or (),
        settings=settings,
    )

    session_id = await sessions.create(
        user,
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

    return MeResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=[r.name for r in user.roles],
    )


__all__ = ["router", "test_router"]
