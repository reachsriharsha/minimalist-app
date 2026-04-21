"""Service-layer helpers for the ``auth`` domain.

Framework-agnostic: accept a session, a redis client, or both; do one
job; return a plain value or model instance. Handlers in
:mod:`app.auth.router` stay thin and delegate here.

Contents:

- :func:`revoke_sessions_for_user` -- thin wrapper over
  :func:`app.auth.sessions.revoke_all_for_user`. Exposed here (rather
  than asking callers to import from ``sessions`` directly) so
  ``feat_auth_003`` can import a stable symbol when it needs to
  invalidate active sessions on a role change or a manual revoke.
- :func:`find_or_create_user_for_otp` (feat_auth_002) -- the real
  find-or-create used by the OTP verify handler. Looks up an
  ``auth_identities`` row first, falls back to finding the user by
  email (and auto-linking a new identity row), and finally creates
  both user + identity + default role (+ admin bootstrap) for a
  brand-new caller.

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

from redis.asyncio import Redis
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.auth.bootstrap import admin_emails_from_settings
from app.auth.models import AuthIdentity, Role, User, UserRole
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


async def find_or_create_user_for_otp(
    session: AsyncSession,
    *,
    email: str,
    settings: Settings,
) -> tuple[User, list[str], bool]:
    """Resolve an OTP-verify caller to a :class:`User` + role names.

    Returns ``(user, sorted_role_names, new_user)``. ``new_user`` is
    ``True`` only when the helper created a brand-new ``users`` row
    in this call -- callers use it for the ``auth.otp.verified``
    structured-log event.

    Resolution order (design-doc §7.1 step 5):

    1. Look up ``auth_identities`` by ``(provider='email',
       provider_user_id=<normalized_email>)``. If found, use
       ``identity.user``.
    2. Otherwise look up ``users`` by email (CITEXT, so case-
       insensitive). If found, **auto-link**: create a new
       ``auth_identities`` row pointing at that user.
    3. Otherwise create a fresh :class:`User`, grant the default
       ``user`` role, apply the ``ADMIN_EMAILS`` bootstrap, and
       create the ``auth_identities`` row.

    Every branch commits the session before returning so the caller
    (the verify handler) never observes a half-committed state.

    Concurrency: two parallel verifies for the same new email can
    both reach branch (3). We guard with an ``IntegrityError`` catch
    and re-read, matching the pattern used elsewhere in this module.
    """

    normalized = (email or "").strip().lower()
    new_user = False

    # ---- 1. Identity lookup ----------------------------------------------
    identity_stmt = select(AuthIdentity).where(
        AuthIdentity.provider == "email",
        AuthIdentity.provider_user_id == normalized,
    )
    identity = (
        await session.execute(identity_stmt)
    ).scalar_one_or_none()

    if identity is not None:
        user = await session.get(User, identity.user_id)
        if user is None:
            # Orphan identity -- treat as if the identity was not
            # there and fall through to create. Extremely unlikely in
            # practice; cascade on ``users`` delete is ``CASCADE``, so
            # the identity should have been deleted too.
            identity = None
        else:
            role_names = await _current_role_names(session, user.id)
            return user, sorted(role_names), False

    # ---- 2. Existing user (no identity yet) ------------------------------
    user_stmt = select(User).where(User.email == normalized)
    user = (await session.execute(user_stmt)).scalar_one_or_none()

    # ---- 3. Create user + bootstrap --------------------------------------
    if user is None:
        user = User(email=normalized, display_name=None)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent creator beat us to it. Re-read and reuse.
            await session.rollback()
            user = (
                await session.execute(user_stmt)
            ).scalar_one_or_none()
            if user is None:
                # Extremely unlikely -- IntegrityError on something
                # other than ``uq_users_email``. Re-raise via a fresh
                # flush so the caller sees the real error.
                user = User(email=normalized, display_name=None)
                session.add(user)
                await session.flush()
            else:
                new_user = False
        else:
            new_user = True

    assert user.id is not None  # flushed above

    role_names = await _current_role_names(session, user.id)

    # Default ``user`` role. ``_grant_role_if_missing`` is idempotent.
    await _grant_role_if_missing(
        session, user.id, "user", already_granted=role_names
    )

    # ADMIN_EMAILS bootstrap (case-insensitive, one-shot on a fresh
    # clone or whenever the listed email first logs in).
    admins = admin_emails_from_settings(settings)
    if normalized in admins:
        await _grant_role_if_missing(
            session, user.id, "admin", already_granted=role_names
        )

    # ---- 4. Ensure the ``email`` auth_identities row exists --------------
    # Recheck with a SELECT + COUNT because the user-create branch above
    # could have happened before the identity-link fallback, and
    # ``auto-link`` needs an insert when the user already existed.
    identity_check = await session.execute(
        select(func.count())
        .select_from(AuthIdentity)
        .where(
            AuthIdentity.user_id == user.id,
            AuthIdentity.provider == "email",
            AuthIdentity.provider_user_id == normalized,
        )
    )
    has_identity = (identity_check.scalar_one() or 0) > 0

    if not has_identity:
        try:
            await session.execute(
                insert(AuthIdentity).values(
                    user_id=user.id,
                    provider="email",
                    provider_user_id=normalized,
                    email_at_identity=normalized,
                )
            )
        except IntegrityError:
            # Concurrent writer inserted the same (provider,
            # provider_user_id) row. No-op for this caller.
            await session.rollback()

    await session.commit()

    return user, sorted(role_names), new_user


__all__ = [
    "revoke_sessions_for_user",
    "find_or_create_user_for_otp",
]
