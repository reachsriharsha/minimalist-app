"""SQLAlchemy ORM models for the ``items`` domain."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Item(Base):
    """Trivial demo entity referenced by the ``/api/v1/hello`` endpoint."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


__all__ = ["Item"]
