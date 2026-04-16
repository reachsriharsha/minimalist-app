"""Verify the ``0002_create_auth`` migration against a real Postgres.

Covers every row in ``test_auth_001.md`` → ``test_migration_0002_auth.py``:

- Clean upgrade produces the four tables and two seed roles.
- Clean downgrade drops the tables (the extension may remain
  installed because Postgres ``DROP EXTENSION`` is ``IF EXISTS``-gated
  above — we verify that the tables are gone).
- ``CITEXT`` gives case-insensitive uniqueness on ``users.email``.
- ``ON DELETE CASCADE`` on user deletion.
- ``ON DELETE RESTRICT`` on role deletion.
- Constraint names match the naming convention.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import build_sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    """Run ``alembic`` as a subprocess from the backend directory."""

    subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        check=True,
    )


@pytest.fixture
async def pg_engine(require_db):
    engine = create_async_engine(require_db)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def upgraded_head(pg_engine):
    """Ensure schema is at ``head`` before the test runs."""

    # Alembic is async-capable in ``env.py``; we call it as a CLI so the
    # subprocess drives the migrations through the configured DSN.
    await asyncio.to_thread(_alembic, "upgrade", "head")
    yield pg_engine
    # Leave the DB at head so subsequent tests (that expect the schema
    # to exist) still pass.


async def test_upgrade_creates_tables_and_seeds_roles(upgraded_head):
    async with upgraded_head.connect() as conn:
        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public'"
                    )
                )
            ).all()
        }
        for expected in {
            "users",
            "roles",
            "user_roles",
            "auth_identities",
        }:
            assert expected in tables, f"{expected} not created"

        role_names = {
            row[0]
            for row in (
                await conn.execute(text("SELECT name FROM roles"))
            ).all()
        }
        assert role_names == {"admin", "user"}

        has_citext = (
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_extension "
                        "WHERE extname='citext'"
                    )
                )
            ).scalar_one()
            == 1
        )
        assert has_citext


async def test_downgrade_then_upgrade(pg_engine, require_db):
    # First: downgrade -1 (to 0001) to drop the auth tables.
    await asyncio.to_thread(_alembic, "downgrade", "0001")

    async with pg_engine.connect() as conn:
        tables = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public'"
                    )
                )
            ).all()
        }
        for gone in {
            "users",
            "roles",
            "user_roles",
            "auth_identities",
        }:
            assert gone not in tables, f"{gone} not dropped"

    # Put the schema back so sibling tests that rely on ``head`` still
    # find the tables.
    await asyncio.to_thread(_alembic, "upgrade", "head")


async def test_email_case_insensitive_uniqueness(upgraded_head):
    # Clean slate for the users table.
    async with upgraded_head.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE auth_identities, user_roles, users "
                "RESTART IDENTITY CASCADE"
            )
        )

    sm = build_sessionmaker(upgraded_head)
    async with sm() as session:
        await session.execute(
            text("INSERT INTO users (email) VALUES ('Alice@X.com')")
        )
        await session.commit()

        with pytest.raises(IntegrityError):
            await session.execute(
                text("INSERT INTO users (email) VALUES ('alice@x.com')")
            )
            await session.commit()
        await session.rollback()


async def test_cascade_on_user_delete(upgraded_head):
    async with upgraded_head.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE auth_identities, user_roles, users "
                "RESTART IDENTITY CASCADE"
            )
        )

    sm = build_sessionmaker(upgraded_head)
    async with sm() as session:
        await session.execute(
            text("INSERT INTO users (id, email) VALUES (1001, 'a@x.com')")
        )
        await session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT 1001, id FROM roles WHERE name='user'"
            )
        )
        await session.execute(
            text(
                "INSERT INTO auth_identities "
                "(user_id, provider, provider_user_id, email_at_identity) "
                "VALUES (1001, 'google', 'xyz', 'a@x.com')"
            )
        )
        await session.commit()

        # Delete the user; cascades should drop both dependent rows.
        await session.execute(text("DELETE FROM users WHERE id=1001"))
        await session.commit()

        remaining_user_roles = (
            await session.execute(
                text("SELECT count(*) FROM user_roles WHERE user_id=1001")
            )
        ).scalar_one()
        assert remaining_user_roles == 0

        remaining_identities = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_identities "
                    "WHERE user_id=1001"
                )
            )
        ).scalar_one()
        assert remaining_identities == 0


async def test_restrict_on_role_delete(upgraded_head):
    # Ensure a row exists referencing the admin role.
    async with upgraded_head.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE auth_identities, user_roles, users "
                "RESTART IDENTITY CASCADE"
            )
        )

    sm = build_sessionmaker(upgraded_head)
    async with sm() as session:
        await session.execute(
            text("INSERT INTO users (id, email) VALUES (1002, 'b@x.com')")
        )
        await session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT 1002, id FROM roles WHERE name='admin'"
            )
        )
        await session.commit()

        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM roles WHERE name='admin'")
            )
            await session.commit()
        await session.rollback()


async def test_constraint_names_match_convention(upgraded_head):
    """Expect pk/uq/fk names wired via ``NAMING_CONVENTION`` in app/db.py."""

    # Pull all constraints from the auth tables and assert the names
    # we care about are present.
    expected_names = {
        "pk_users",
        "uq_users_email",
        "pk_roles",
        "uq_roles_name",
        "pk_user_roles",
        "fk_user_roles_user_id_users",
        "fk_user_roles_role_id_roles",
        "pk_auth_identities",
        "fk_auth_identities_user_id_users",
        "uq_auth_identities_provider",
    }

    async with upgraded_head.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid::regclass::text "
                    "IN ('users','roles','user_roles','auth_identities')"
                )
            )
        ).all()

    actual = {row[0] for row in rows}
    missing = expected_names - actual
    assert not missing, f"expected constraint names missing: {missing}"
