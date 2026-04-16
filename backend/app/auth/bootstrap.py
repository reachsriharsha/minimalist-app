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

The user-creation code path itself lives in the test-only mint
(``POST /api/v1/_test/session``) and will later live in
``feat_auth_002`` (OTP verify) and ``feat_auth_003`` (OAuth callback).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
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
    calling twice in sequence never adds a second ``admin`` row to
    ``user.roles``.

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

    if any(role.name == "admin" for role in user.roles):
        # Already an admin — nothing to do. Preserves idempotency.
        return False

    result = await session.execute(select(Role).where(Role.name == "admin"))
    admin_role = result.scalar_one_or_none()
    if admin_role is None:
        # The migration seeds ``admin``; if it is missing, the database
        # is not in the expected state. Refuse silently rather than
        # creating a role row here, which belongs to the migration.
        return False

    user.roles.append(admin_role)
    await session.flush()
    return True


__all__ = ["admin_emails_from_settings", "grant_admin_if_listed"]
