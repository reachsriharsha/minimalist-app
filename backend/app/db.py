"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_ASYNC_DRIVERS = ("+asyncpg", "+aiosqlite", "+asyncmy", "+asyncodbc")


def _validate_async_url(url: str) -> None:
    """Reject sync driver URLs with a pointed error message.

    The scaffold is intentionally async end-to-end. Accepting a sync URL here
    would defer the failure to the first query and emit confusing diagnostics.
    """

    if "://" not in url:
        raise ValueError(
            f"DATABASE_URL must be a SQLAlchemy URL; got {url!r}"
        )
    scheme = url.split("://", 1)[0]
    if any(marker in scheme for marker in _ASYNC_DRIVERS):
        return
    raise ValueError(
        "DATABASE_URL must use an async driver. "
        f"Got scheme {scheme!r}; expected something like "
        "'postgresql+asyncpg://user:pass@host:5432/db'."
    )


def build_engine(database_url: str) -> AsyncEngine:
    """Construct the async engine without opening a connection."""

    _validate_async_url(database_url)
    # ``create_async_engine`` itself does not open a connection — the pool is
    # lazy, which is what the scaffold's startup story relies on.
    return create_async_engine(database_url, pool_pre_ping=True, future=True)


def build_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Construct the session factory bound to ``engine``."""

    return async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a short-lived :class:`AsyncSession`."""

    sessionmaker: async_sessionmaker[AsyncSession] = (
        request.app.state.sessionmaker
    )
    async with sessionmaker() as session:
        yield session


__all__ = [
    "build_engine",
    "build_sessionmaker",
    "get_session",
]
