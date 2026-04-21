"""``ADMIN_EMAILS`` bootstrap hook.

Design reference: §7.7 of ``docs/design/auth-login-and-roles.md``.

Controls the *first time a user is created*, not every login and not on
settings reload. Demotion requires a DB write; promotion after launch
requires a DB write. The env var is a bootstrap seed, deliberately not
a live sync — see §15 of the design doc.

This module is intentionally small. It:

1. Parses :attr:`Settings.admin_emails` into a lower-cased set (the
   settings property already does this, but we expose a helper so call
   sites do not have to remember the attribute name).
2. Grants an ``admin`` role to a freshly-created user whose email
   appears in that set, idempotently.

The user-creation code path lives in ``feat_auth_002`` (OTP verify, via
``app.auth.service.find_or_create_user_for_otp``) and will extend to
``feat_auth_003`` (OAuth callback) when Google login lands.

Implementation note: all role-set manipulation goes through explicit
SELECT/INSERT on the association table, not through the ORM relationship
accessor :attr:`app.auth.models.User.roles`. Touching that attribute on a
freshly-created, async-session-bound :class:`User` raises
``MissingGreenlet`` because SQLAlchemy's implicit lazy-load path is not
bridged to ``await`` when you access it as a plain attribute. See
``backend/app/auth/service.py`` for the same pattern.
"""

from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserRole
from app.settings import Settings


def admin_emails_from_settings(settings: Settings) -> frozenset[str]:
    """Return the lower-cased set of bootstrap-admin addresses.

    Thin accessor for the settings property; exposed so callers do not
    have to know where the parsing lives. Empty settings produces an
    empty set.
    """

    return settings.admin_emails_set


async def grant_admin_if_listed(
    user: User,
    *,
    session: AsyncSession,
    settings: Settings,
) -> bool:
    """Grant the ``admin`` role to ``user`` if their email is listed.

    Returns ``True`` when a grant actually happened (the email matched
    and the user did not already have the role), ``False`` otherwise.

    The check is case-insensitive: the settings side lower-cases the
    listed addresses and we lower-case ``user.email`` here. Idempotent:
    calling twice in sequence never adds a second ``admin`` row.

    The caller is responsible for committing the transaction. This
    helper flushes so the new association is visible to subsequent
    reads within the same session.
    """

    admins = admin_emails_from_settings(settings)
    if not admins:
        return False

    normalised = (user.email or "").strip().lower()
    if normalised not in admins:
        return False

    # Look up the ``admin`` role by name. Migration seeds it, so the
    # row exists on a healthy database.
    admin_row = (
        await session.execute(select(Role.id).where(Role.name == "admin"))
    ).scalar_one_or_none()
    if admin_row is None:
        return False

    # Check idempotency via a direct query on the association table —
    # avoids triggering a lazy-load on ``user.roles`` from an async
    # session.
    existing = (
        await session.execute(
            select(UserRole.role_id).where(
                UserRole.user_id == user.id,
                UserRole.role_id == admin_row,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    try:
        await session.execute(
            insert(UserRole).values(user_id=user.id, role_id=admin_row)
        )
        await session.flush()
    except IntegrityError:
        # Race: someone else just inserted the same row. Treat as a
        # no-op grant (the caller wanted admin, admin is now present).
        await session.rollback()
        return False

    return True


__all__ = ["admin_emails_from_settings", "grant_admin_if_listed"]
