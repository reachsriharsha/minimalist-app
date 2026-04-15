"""``GET /api/v1/hello`` — round-trips Postgres and Redis in a single request."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Item
from app.redis_client import get_redis
from app.schemas import HelloResponse

router = APIRouter(tags=["hello"])

HELLO_COUNTER_KEY = "hello:count"


@router.get("/hello", response_model=HelloResponse)
async def hello(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HelloResponse:
    """Read the seeded item, increment the Redis counter, return both."""

    result = await session.execute(select(Item).where(Item.id == 1))
    item = result.scalar_one_or_none()
    if item is None:
        # The scaffold seeds id=1 in migration 0001. If it is missing the
        # database is not in the expected state for this endpoint.
        raise HTTPException(
            status_code=503,
            detail="seed item missing; run 'alembic upgrade head'",
        )

    new_count = await redis.incr(HELLO_COUNTER_KEY)

    return HelloResponse(
        message="hello from minimalist-app",
        item_name=item.name,
        hello_count=int(new_count),
    )


__all__ = ["router", "HELLO_COUNTER_KEY"]
