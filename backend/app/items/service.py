"""Service-layer helpers for the ``items`` domain.

Framework-agnostic: accept a session or redis client, do one job, return a
plain value. Handlers in :mod:`app.items.router` stay thin and delegate here.
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.items.models import Item

HELLO_COUNTER_KEY = "hello:count"


async def get_seed_item(session: AsyncSession) -> Item | None:
    """Fetch the seeded ``items`` row with ``id == 1``.

    Returns ``None`` if the row is missing; callers decide how to surface that.
    """

    result = await session.execute(select(Item).where(Item.id == 1))
    return result.scalar_one_or_none()


async def increment_hello_counter(redis: Redis) -> int:
    """Increment the ``hello:count`` key in Redis and return the new value."""

    return int(await redis.incr(HELLO_COUNTER_KEY))


__all__ = ["HELLO_COUNTER_KEY", "get_seed_item", "increment_hello_counter"]
