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

Note on async-session + relationships: in SQLAlchemy 2.x, accessing a
relationship attribute (``user.roles``) on an instance whose collection
has not yet been loaded triggers a lazy SELECT. When the parent session
is async, that implicit SELECT goes through the greenlet-bridged
``await_only`` and raises ``MissingGreenlet`` if called from bare
attribute access. We therefore load role *names* via explicit SELECTs
over the ``user_roles`` association table, never via the ORM
relationship accessor inside this module.
"""

from __future__ import annotations

from typing import Iterable

from redis.asyncio import Redis
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.auth.bootstrap import admin_emails_from_settings
from app.auth.models import Role, User, UserRole
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


async def _current_role_names(
    session: AsyncSession, user_id: int
) -> set[str]:
    """Return the set of role names currently granted to ``user_id``.

    Reads via an explicit SELECT join over ``user_roles`` / ``roles`` so
    this is safe to call on a freshly-created user in an async session
    without triggering an implicit lazy-load greenlet error.
    """

    result = await session.execute(
        select(Role.name)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )
    return {name for (name,) in result.all()}


async def _grant_role_if_missing(
    session: AsyncSession,
    user_id: int,
    role_name: str,
    *,
    already_granted: set[str],
) -> bool:
    """Idempotently insert a ``user_roles`` row.

    Returns ``True`` when an insert actually happened. ``already_granted``
    is the caller-supplied set of existing role names for the user; we
    mutate it in place on a successful grant so sequential calls stay
    coherent without a re-read.
    """

    if role_name in already_granted:
        return False

    result = await session.execute(
        select(Role.id).where(Role.name == role_name)
    )
    role_id = result.scalar_one_or_none()
    if role_id is None:
        # Migration seeds ``admin`` and ``user``; anything else is a
        # caller bug (unknown role). Skip silently rather than erroring.
        return False

    try:
        await session.execute(
            insert(UserRole).values(user_id=user_id, role_id=role_id)
        )
    except IntegrityError:
        # Row already exists under a concurrent writer. Keep the state
        # the caller believes they have.
        await session.rollback()
        already_granted.add(role_name)
        return False

    already_granted.add(role_name)
    return True


async def find_or_create_user_for_test(
    session: AsyncSession,
    *,
    email: str,
    display_name: str | None,
    extra_roles: Iterable[str] = (),
    settings: Settings,
) -> tuple[User, list[str]]:
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

    Returns a ``(user, role_names)`` pair so callers can build a session
    payload without touching the lazy-loaded :attr:`User.roles`
    collection on the still-live async session.
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
            await session.rollback()
            result = await session.execute(stmt)
            user = result.scalar_one()

    assert user.id is not None  # flushed above

    role_names = await _current_role_names(session, user.id)

    # Always ensure the default ``user`` role.
    await _grant_role_if_missing(
        session, user.id, "user", already_granted=role_names
    )

    # ADMIN_EMAILS bootstrap (case-insensitive membership test).
    admins = admin_emails_from_settings(settings)
    if (email or "").strip().lower() in admins:
        await _grant_role_if_missing(
            session, user.id, "admin", already_granted=role_names
        )

    # Extra caller-specified roles (unknown names are silently skipped
    # inside ``_grant_role_if_missing``).
    for name in extra_roles or ():
        if not name:
            continue
        await _grant_role_if_missing(
            session, user.id, name, already_granted=role_names
        )

    await session.commit()

    return user, sorted(role_names)


__all__ = [
    "revoke_sessions_for_user",
    "find_or_create_user_for_test",
]
