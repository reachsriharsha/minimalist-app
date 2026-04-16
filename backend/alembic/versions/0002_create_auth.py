"""create auth tables (users, roles, user_roles, auth_identities) and citext

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16

Per ``docs/specs/feat_auth_001/design_auth_001.md`` and §6.1 of
``docs/design/auth-login-and-roles.md``:

- Installs the ``citext`` Postgres extension (idempotent).
- Creates ``users``, ``roles``, ``user_roles``, ``auth_identities``.
- Seeds two role rows, ``admin`` and ``user``.
- Uses the naming convention wired onto ``Base.metadata`` in
  ``feat_backend_002`` (``app/db.py``), so constraint names are
  deterministic (``pk_users``, ``uq_users_email``, etc.).

Note: ``downgrade`` drops the ``citext`` extension because this migration
is the first to install it. A future migration that also needs ``citext``
must use ``CREATE EXTENSION IF NOT EXISTS`` (as this file does) so it is
safe to run after a partial downgrade that left the extension around.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CITEXT = sa.dialects.postgresql.CITEXT  # type: ignore[attr-defined]


def upgrade() -> None:
    # 1. Install the CITEXT extension. Idempotent so re-running the migration
    #    against a database that already has it (e.g., some future 0003 also
    #    needs it) is a no-op.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # 2. users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # 3. roles
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    # Seed the two bootstrap roles. Order is deterministic so the IDs are
    # predictable in a fresh database: admin=1, user=2. Tests should not
    # depend on those IDs directly; they look up by name.
    op.bulk_insert(
        roles,
        [
            {"name": "admin"},
            {"name": "user"},
        ],
    )

    # 4. user_roles (association)
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "role_id", name="pk_user_roles"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_roles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_user_roles_role_id_roles",
            ondelete="RESTRICT",
        ),
    )

    # 5. auth_identities
    op.create_table(
        "auth_identities",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_user_id", sa.String(length=255), nullable=False
        ),
        sa.Column("email_at_identity", CITEXT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_identities_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_auth_identities_provider",
        ),
    )
    op.create_index(
        "ix_auth_identities_user_id",
        "auth_identities",
        ["user_id"],
    )


def downgrade() -> None:
    # Drop in reverse creation order so FKs unwind cleanly.
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    # Drop the CITEXT extension last. If another migration in the future
    # needs citext, it must CREATE EXTENSION IF NOT EXISTS on upgrade so it
    # is safe whether or not this downgrade has run.
    op.execute("DROP EXTENSION IF EXISTS citext")
