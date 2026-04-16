"""SQLAlchemy ORM models for the ``auth`` domain.

Mirrors the migration in ``alembic/versions/0002_create_auth.py``.

The schema is specified in §6.1 of ``docs/design/auth-login-and-roles.md``:

- ``User``: opaque numeric id, case-insensitive email (``CITEXT``), optional
  display name, timestamps.
- ``Role``: small lookup table; seeded with ``admin`` and ``user``.
- ``UserRole``: association table with a composite PK and cascade
  behavior matching the migration (``CASCADE`` on user delete, ``RESTRICT``
  on role delete).
- ``AuthIdentity``: provider-specific identity linked to a user; unique
  on ``(provider, provider_user_id)``.

``User.roles`` is loaded via the association table so call sites can
write ``[r.name for r in user.roles]`` without touching ``UserRole``
directly. Session-creation code uses that list to build the session
payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


class User(Base):
    """Application user identified by a case-insensitive email."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    # ``secondary`` association keeps the relationship a plain ``list[Role]``
    # so callers do not need to know about ``UserRole``. ``lazy="selectin"``
    # issues one extra SELECT per query on load; it is cheap at scaffold
    # scale and removes a surprise N+1 when callers iterate ``user.roles``.
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary="user_roles",
        lazy="selectin",
    )

    identities: Mapped[list["AuthIdentity"]] = relationship(
        "AuthIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Role(Base):
    """Named role; the small lookup table for ``user_roles``."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)


class UserRole(Base):
    """Association between :class:`User` and :class:`Role`.

    Composite primary key ``(user_id, role_id)`` matches the migration.
    """

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AuthIdentity(Base):
    """Provider-specific identity (Google, email-OTP, ...) linked to a user.

    Unique on ``(provider, provider_user_id)`` so a single provider account
    maps to exactly one internal user. ``email_at_identity`` records the
    email the provider returned at link time — not kept in sync with
    :attr:`User.email`, so account-linking decisions can be audited later.
    """

    __tablename__ = "auth_identities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    email_at_identity: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_auth_identities_provider",
        ),
    )

    user: Mapped[User] = relationship("User", back_populates="identities")


__all__ = ["User", "Role", "UserRole", "AuthIdentity"]
