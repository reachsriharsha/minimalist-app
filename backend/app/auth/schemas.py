"""Schemas and in-memory shapes used by the ``auth`` domain.

Design references:

- ``AuthContext``: frozen dataclass describing the authenticated principal
  for a single request. Lives on ``request.state.auth`` (or is ``None`` if
  the request is anonymous) and is consumed by :mod:`app.auth.dependencies`.
  See ``docs/specs/feat_auth_001/design_auth_001.md`` -> "``AuthContext``
  shape" and §2 of ``docs/design/auth-login-and-roles.md`` (role data in
  the session payload, no per-request DB hit).
- ``MeResponse``: payload shape for ``GET /api/v1/auth/me`` per §7.3 of
  the design doc.
- ``OtpRequestIn`` / ``OtpVerifyIn`` (feat_auth_002): request bodies for
  the two OTP endpoints. Share the ``_validate_email_shape`` helper with
  legacy call sites so there is one place to evolve email validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authenticated principal for a single request.

    Frozen + slotted -> cheap, hashable, explicitly immutable. ``roles`` is
    a tuple (not a list) so the context can be shared across dependency
    calls without concern for mutation.
    """

    user_id: int
    email: str
    roles: tuple[str, ...]
    session_id: str


# Minimal email sanity check. We deliberately do not pull in
# ``email-validator`` (pydantic's ``EmailStr`` backing) because the real
# login paths (OTP in 002, OAuth in 003) do provider-side verification
# anyway. This check only guards the wire-level shape of request bodies.
_EMAIL_SHAPE = "@"


def _validate_email_shape(value: str) -> str:
    value = value.strip()
    if _EMAIL_SHAPE not in value or len(value) < 3:
        raise ValueError("not a valid email")
    return value


class MeResponse(BaseModel):
    """Response body for ``GET /api/v1/auth/me``.

    Shape fixed by §7.3 of the design doc.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: int
    email: str
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)


class OtpRequestIn(BaseModel):
    """Request body for ``POST /api/v1/auth/otp/request``.

    ``extra="forbid"`` so typos like ``{"emial": "..."}`` produce a
    clean 422 rather than silently dropping the field.
    """

    model_config = ConfigDict(extra="forbid")

    email: str

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        return _validate_email_shape(v)


class OtpVerifyIn(BaseModel):
    """Request body for ``POST /api/v1/auth/otp/verify``.

    The ``code`` field is validated as "exactly six ASCII digits". Any
    other shape raises a :class:`ValueError` that the router converts
    to the uniform ``400 invalid_or_expired_code`` response -- we never
    let a 422 leak because it would distinguish "shape wrong" from
    "wrong code", violating the enumeration-resistance rule in
    design-doc §7.1.
    """

    model_config = ConfigDict(extra="forbid")

    email: str
    code: str

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        return _validate_email_shape(v)

    @field_validator("code")
    @classmethod
    def _code_shape(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) != 6 or not v.isdigit():
            # Same failure mode as wrong code. The router maps this
            # ValueError to a 400 ``invalid_or_expired_code`` body --
            # do not leak "validation" vs "wrong-code".
            raise ValueError("invalid_or_expired_code")
        return v


__all__ = [
    "AuthContext",
    "MeResponse",
    "OtpRequestIn",
    "OtpVerifyIn",
]
