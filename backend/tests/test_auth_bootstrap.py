"""Unit tests for :mod:`app.auth.bootstrap`.

Covers every case in ``test_auth_001.md`` → ``test_auth_bootstrap.py``.
Each test exercises ``grant_admin_if_listed`` against a fresh session
opened on the real test database.

Note on role readback: we verify role membership by re-reading the
``user_roles`` association table with an explicit JOIN, rather than by
touching :attr:`User.roles` on the async-session-live instance. The ORM
relationship's implicit lazy load is not bridged to ``await`` in
SQLAlchemy 2.x async sessions (``MissingGreenlet``), and this module is
the one that enforces that the *production* code goes through explicit
SELECTs — so the test suite follows the same rule.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.bootstrap import (
    admin_emails_from_settings,
    grant_admin_if_listed,
)
from app.auth.models import Role, User, UserRole
from app.db import build_sessionmaker
from app.settings import Settings, reset_settings_cache


@pytest.fixture
async def db_session(require_db):
    """Yield an ``AsyncSession`` bound to the configured test database.

    Each test starts from a clean ``users`` / ``user_roles`` state.
    """

    engine = create_async_engine(require_db)
    try:
        sm = build_sessionmaker(engine)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE auth_identities, user_roles, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
        async with sm() as session:
            yield session
    finally:
        await engine.dispose()


async def _make_user(
    session, email: str, display_name: str | None = None
) -> User:
    """Insert a fresh :class:`User` with no roles attached."""

    user = User(email=email, display_name=display_name)
    session.add(user)
    await session.flush()
    return user


async def _role_names(session, user_id: int) -> set[str]:
    """Return the role names currently granted to ``user_id``."""

    result = await session.execute(
        select(Role.name)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )
    return {name for (name,) in result.all()}


def _settings(admin_emails: str) -> Settings:
    """Build a ``Settings`` instance without touching env vars."""

    return Settings(admin_emails=admin_emails)


async def test_empty_admin_emails_never_grants(db_session):
    """Case 1: empty list is a no-op."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert granted is False
    assert await _role_names(db_session, user.id) == set()


async def test_exact_match_grants(db_session):
    """Case 2: email in the list grants the ``admin`` role."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("alice@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert granted is True
    assert "admin" in await _role_names(db_session, user.id)


async def test_case_insensitive_match(db_session):
    """Case 3: case differences in the env list still grant."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("ALICE@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert granted is True
    assert "admin" in await _role_names(db_session, user.id)


async def test_whitespace_tolerant(db_session):
    """Case 4: leading/trailing whitespace is stripped per entry."""

    user = await _make_user(db_session, "bob@x.com")
    settings = _settings(" alice@x.com , bob@x.com ")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert granted is True
    assert "admin" in await _role_names(db_session, user.id)


async def test_non_member_not_granted(db_session):
    """Case 5: an email not in the list is not granted admin."""

    user = await _make_user(db_session, "carol@x.com")
    settings = _settings("alice@x.com,bob@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert granted is False
    assert "admin" not in await _role_names(db_session, user.id)


def test_settings_cache_reflects_env(monkeypatch):
    """Case 6: resetting the cache after ``monkeypatch.setenv`` picks up the
    new value."""

    from app.settings import get_settings

    monkeypatch.setenv("ADMIN_EMAILS", "first@x.com")
    reset_settings_cache()
    try:
        s1 = get_settings()
        assert "first@x.com" in s1.admin_emails_set

        monkeypatch.setenv("ADMIN_EMAILS", "second@x.com")
        reset_settings_cache()

        s2 = get_settings()
        assert "second@x.com" in s2.admin_emails_set
        assert "first@x.com" not in s2.admin_emails_set
    finally:
        reset_settings_cache()


async def test_idempotent_grant(db_session):
    """Case 7: calling twice does not produce two ``admin`` rows."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("alice@x.com")

    first = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    second = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )
    await db_session.commit()

    assert first is True
    # Second call returns False because the role is already present.
    assert second is False

    # Exactly one row in user_roles linking user -> admin role.
    result = await db_session.execute(
        select(UserRole).where(UserRole.user_id == user.id)
    )
    rows = result.scalars().all()
    admin_ids = {
        r[0]
        for r in (
            await db_session.execute(
                select(Role.id).where(Role.name == "admin")
            )
        ).all()
    }
    admin_rows = [r for r in rows if r.role_id in admin_ids]
    assert len(admin_rows) == 1


def test_admin_emails_from_settings_helper():
    """The helper is a thin pass-through to the settings property."""

    s = _settings("  a@x.com, B@x.com ,, c@x.com  ")
    got = admin_emails_from_settings(s)
    assert got == frozenset({"a@x.com", "b@x.com", "c@x.com"})
