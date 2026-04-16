"""Unit tests for :mod:`app.auth.bootstrap`.

Covers every case in ``test_auth_001.md`` → ``test_auth_bootstrap.py``.
Each test exercises ``grant_admin_if_listed`` against a fresh session
opened on the real test database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.bootstrap import (
    admin_emails_from_settings,
    grant_admin_if_listed,
)
from app.auth.models import User
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
            # Truncate with CASCADE to reset ``users``, ``user_roles``,
            # and ``auth_identities`` between tests without touching
            # ``roles`` (which is seeded by the migration).
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

    assert granted is False
    assert [r.name for r in user.roles] == []


async def test_exact_match_grants(db_session):
    """Case 2: email in the list grants the ``admin`` role."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("alice@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )

    assert granted is True
    assert "admin" in [r.name for r in user.roles]


async def test_case_insensitive_match(db_session):
    """Case 3: case differences in the env list still grant."""

    user = await _make_user(db_session, "alice@x.com")
    settings = _settings("ALICE@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )

    assert granted is True
    assert "admin" in [r.name for r in user.roles]


async def test_whitespace_tolerant(db_session):
    """Case 4: leading/trailing whitespace is stripped per entry."""

    user = await _make_user(db_session, "bob@x.com")
    settings = _settings(" alice@x.com , bob@x.com ")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )

    assert granted is True
    assert "admin" in [r.name for r in user.roles]


async def test_non_member_not_granted(db_session):
    """Case 5: an email not in the list is not granted admin."""

    user = await _make_user(db_session, "carol@x.com")
    settings = _settings("alice@x.com,bob@x.com")

    granted = await grant_admin_if_listed(
        user, session=db_session, settings=settings
    )

    assert granted is False
    assert "admin" not in [r.name for r in user.roles]


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

    assert first is True
    # Second call returns False because the role is already present.
    assert second is False

    admin_count = sum(1 for r in user.roles if r.name == "admin")
    assert admin_count == 1


def test_admin_emails_from_settings_helper():
    """The helper is a thin pass-through to the settings property."""

    s = _settings("  a@x.com, B@x.com ,, c@x.com  ")
    got = admin_emails_from_settings(s)
    assert got == frozenset({"a@x.com", "b@x.com", "c@x.com"})
