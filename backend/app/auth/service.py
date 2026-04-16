"""Service-layer helpers for the ``auth`` domain.

Framework-agnostic: accept a session, a redis client, or both; do one
job; return a plain value or model instance. Handlers in
:mod:`app.auth.router` stay thin and delegate here.

Contents:

- :func:`revoke_sessions_for_user` — thin wrapper over
  :func:`app.auth.sessions.revoke_all_for_user`. Exposed here (rather
  than asking callers to import from ``sessions`` directly) so
  ``feat_auth_002`` and ``feat_auth_003`` can import a stable symbol
  when they need to invalidate active sessions on a role change or a
  manual revoke.
- :func:`find_or_create_user_for_test` — find-or-create helper used by
  the env-gated test-only mint endpoint. Applies ``ADMIN_EMAILS``
  bootstrap on first creation and optionally grants extra roles.
  Not a general-purpose helper; real login paths (002, 003) create
  their own find-or-create plus identity-linking routines.
"""

from __future__ import annotations

from typing import Iterable

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.auth.bootstrap import grant_admin_if_listed
from app.auth.models import Role, User
from app.settings import Settings


async def revoke_sessions_for_user(
    user_id: int,
    *,
    redis: Redis,
) -> None:
    """Invalidate every active session for ``user_id``.

    Deliberately ``DEL``-based (not update-based): no races, no stale
    caches. See §7.6 of ``docs/design/auth-login-and-roles.md``.
    """

    await sessions.revoke_all_for_user(user_id, redis=redis)


async def _ensure_user_role(session: AsyncSession, user: User) -> None:
    """Ensure ``user`` has the default ``user`` role."""

    if any(r.name == "user" for r in user.roles):
        return
    result = await session.execute(select(Role).where(Role.name == "user"))
    role = result.scalar_one_or_none()
    if role is None:
        # Migration seeds the role; missing seed is a bug in ops, not
        # something we silently paper over by creating the row here.
        return
    user.roles.append(role)
    await session.flush()


async def _grant_extra_roles(
    session: AsyncSession,
    user: User,
    names: Iterable[str],
) -> None:
    """Grant each named role to ``user`` (case-sensitive; unknown skipped)."""

    wanted = {n for n in names if n}
    wanted.discard("user")  # handled by ``_ensure_user_role``
    if not wanted:
        return

    existing = {r.name for r in user.roles}
    to_grant = wanted - existing
    if not to_grant:
        return

    result = await session.execute(
        select(Role).where(Role.name.in_(to_grant))
    )
    for role in result.scalars().all():
        user.roles.append(role)
    await session.flush()


async def find_or_create_user_for_test(
    session: AsyncSession,
    *,
    email: str,
    display_name: str | None,
    extra_roles: Iterable[str] = (),
    settings: Settings,
) -> User:
    """Find or create a :class:`User` for the test-only mint endpoint.

    Semantics:

    - Lookup is case-insensitive (``email`` is stored as ``CITEXT``).
    - If the user exists, reuse it. Applying extra roles and the
      ``ADMIN_EMAILS`` bootstrap on an existing user is deliberately
      idempotent: a second mint does not add a second ``admin`` row and
      does not downgrade the user.
    - If the user does not exist, create them, grant the default ``user``
      role, apply the ``ADMIN_EMAILS`` bootstrap, and grant any extra
      roles. A concurrent second creation for the same email is
      tolerated via a ``UNIQUE`` violation + re-read.
    - Does **not** create an ``auth_identities`` row. Identity rows
      belong to real login paths (002/003).
    """

    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email, display_name=display_name)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # A concurrent mint created the row first. Rolling back the
            # nested state and re-reading is simpler than SAVEPOINT-ing
            # the insert. Matches §7.7 of the design doc's guidance.
            await session.rollback()
            result = await session.execute(stmt)
            user = result.scalar_one()

    # Always ensure defaults. These are all idempotent when the user
    # already has the role, so a second mint is a no-op.
    await _ensure_user_role(session, user)
    await grant_admin_if_listed(user, session=session, settings=settings)
    await _grant_extra_roles(session, user, extra_roles)

    await session.commit()
    # Re-fetch to make ``user.roles`` reflect the committed state. With
    # ``expire_on_commit=False`` on the sessionmaker (see ``app/db.py``),
    # the attribute collection is still valid — but a selectin-loaded
    # relationship is lazy on first access, so we trigger it here.
    _ = user.roles  # noqa: B018 - force selectin load
    return user


__all__ = [
    "revoke_sessions_for_user",
    "find_or_create_user_for_test",
]
