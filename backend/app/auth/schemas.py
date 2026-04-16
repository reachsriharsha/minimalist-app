"""Schemas and in-memory shapes used by the ``auth`` domain.

Design references:

- ``AuthContext``: frozen dataclass describing the authenticated principal
  for a single request. Lives on ``request.state.auth`` (or is ``None`` if
  the request is anonymous) and is consumed by :mod:`app.auth.dependencies`.
  See ``docs/specs/feat_auth_001/design_auth_001.md`` → "``AuthContext``
  shape" and §2 of ``docs/design/auth-login-and-roles.md`` (role data in
  the session payload, no per-request DB hit).
- ``MeResponse``: payload shape for ``GET /api/v1/auth/me`` per §7.3 of
  the design doc.
- ``TestSessionRequest``: request body for the env-gated test-only mint
  endpoint. Removed in ``feat_auth_002``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, EmailStr, Field


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authenticated principal for a single request.

    Frozen + slotted → cheap, hashable, explicitly immutable. ``roles`` is
    a tuple (not a list) so the context can be shared across dependency
    calls without concern for mutation.
    """

    user_id: int
    email: str
    roles: tuple[str, ...]
    session_id: str


class MeResponse(BaseModel):
    """Response body for ``GET /api/v1/auth/me``.

    Shape fixed by §7.3 of the design doc.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: int
    email: EmailStr
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)


class TestSessionRequest(BaseModel):
    """Request body for the test-only ``POST /api/v1/_test/session`` endpoint.

    Only mounted when ``settings.env == "test"``. See
    ``docs/specs/feat_auth_001/feat_auth_001.md`` requirement 11.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str | None = None
    # Additional roles to grant beyond the default ``user`` role and any
    # bootstrap ``admin`` grant from ``ADMIN_EMAILS``. Names are matched
    # against :class:`Role.name` — unknown names are silently skipped.
    roles: list[str] | None = None


__all__ = ["AuthContext", "MeResponse", "TestSessionRequest"]
