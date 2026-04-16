"""``GET /hello`` — round-trips Postgres and Redis in a single request.

This router is mounted under ``/api/v1/`` by :mod:`app.api.v1`. The handler
stays thin: it resolves dependencies, delegates to :mod:`app.items.service`,
and shapes a :class:`HelloResponse`. External behavior is identical to the
pre-``feat_backend_002`` ``app/api/v1/hello.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.items import service
from app.items.schemas import HelloResponse
from app.redis_client import get_redis

router = APIRouter(tags=["items"])


@router.get("/hello", response_model=HelloResponse)
async def hello(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HelloResponse:
    """Read the seeded item, increment the Redis counter, return both."""

    item = await service.get_seed_item(session)
    if item is None:
        # The scaffold seeds id=1 in migration 0001. If it is missing the
        # database is not in the expected state for this endpoint.
        raise HTTPException(
            status_code=503,
            detail="seed item missing; run 'alembic upgrade head'",
        )

    count = await service.increment_hello_counter(redis)

    return HelloResponse(
        message="hello from minimalist-app",
        item_name=item.name,
        hello_count=count,
    )


__all__ = ["router"]
