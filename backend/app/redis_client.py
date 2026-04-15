"""Async Redis client construction and FastAPI dependency."""

from __future__ import annotations

from fastapi import Request
from redis.asyncio import Redis, from_url


def build_redis(redis_url: str) -> Redis:
    """Build an async :class:`Redis` client.

    The client is lazy: constructing it does not open a socket. The first
    command (or an explicit ``ping``) establishes the connection.
    """

    return from_url(redis_url, encoding="utf-8", decode_responses=True)


async def get_redis(request: Request) -> Redis:
    """FastAPI dependency returning the shared Redis client."""

    return request.app.state.redis


__all__ = ["build_redis", "get_redis"]
