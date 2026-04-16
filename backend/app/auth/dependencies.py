"""FastAPI dependencies for authentication and authorization.

These are the only call sites that need to know how auth data gets onto
``request.state``. Route handlers use them like any other dependency:

.. code-block:: python

    @router.get("/me")
    async def me(ctx: AuthContext = Depends(current_user)) -> MeResponse:
        ...

All three helpers are zero-DB: they read from
``request.state.auth``, which :class:`app.middleware.SessionMiddleware`
populates from a single Redis ``GET``. See §2 of
``docs/design/auth-login-and-roles.md``.

Precedence rule: **authentication before authorization**. Even when a
route uses ``require_roles(...)``, a request with no session returns
``401 not_authenticated``, not ``403 forbidden``. That is the right
default — a 403 on an unauthenticated request leaks "this is a
protected endpoint" to a scanner.
"""

from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, Request, status

from app.auth.schemas import AuthContext


def current_user(request: Request) -> AuthContext:
    """Return the authenticated principal or raise ``401``.

    Reads :attr:`request.state.auth`, which
    :class:`app.middleware.SessionMiddleware` has already populated in
    this request's lifecycle. No DB hit.
    """

    ctx = getattr(request.state, "auth", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not_authenticated",
        )
    return ctx


# Same behaviour as :func:`current_user`; exported under a more readable
# name for routes that only need "must be logged in" semantics without
# using the context value.
require_authenticated = current_user


def require_roles(*names: str) -> Callable[[Request], AuthContext]:
    """Build a dependency that enforces OR semantics across ``names``.

    Usage::

        @router.get(..., dependencies=[Depends(require_roles("admin"))])
        ...

    Semantics:

    - If there is no session, raise ``401 not_authenticated``
      (authentication precedes authorization).
    - Otherwise, if **any** of the required role names appears in the
      session payload's ``roles``, the request is allowed.
    - Otherwise, raise ``403 forbidden``.
    """

    required = frozenset(names)

    def _dependency(request: Request) -> AuthContext:
        ctx = getattr(request.state, "auth", None)
        if ctx is None:
            # Unauthenticated takes precedence over unauthorized.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not_authenticated",
            )
        if required and required.isdisjoint(ctx.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden",
            )
        return ctx

    return _dependency


__all__ = [
    "current_user",
    "require_authenticated",
    "require_roles",
]
