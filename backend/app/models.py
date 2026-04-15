"""SQLAlchemy ORM models for the scaffold."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models in the backend package."""


class Item(Base):
    """Trivial demo entity referenced by the ``/api/v1/hello`` endpoint."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


__all__ = ["Base", "Item"]
