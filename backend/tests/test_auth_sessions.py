"""Unit tests for :mod:`app.auth.sessions`.

These are "unit" tests in the sense that they exercise the Redis store
helpers directly — no FastAPI app, no middleware — but they *do* talk to
a real Redis. If Redis is unreachable at the configured URL the whole
module is skipped. Matches the existing scaffold's ``require_redis``
pattern.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from redis.asyncio import from_url

from app.auth import sessions
from app.auth.schemas import AuthContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis(require_redis):
    """A per-test Redis client tied to the configured URL.

    Flushes the current DB before and after so a test never sees keys
    left over from a prior run.
    """

    client = from_url(require_redis, encoding="utf-8", decode_responses=True)
    try:
        await client.flushdb()
        yield client
        await client.flushdb()
    finally:
        await client.aclose()


def _user_like(user_id: int, email: str, role_names: list[str]) -> Any:
    """Return an object with the attributes ``sessions.create`` reads."""

    roles = [SimpleNamespace(name=n) for n in role_names]
    return SimpleNamespace(id=user_id, email=email, roles=roles)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_round_trip(redis):
    """Case 1: create writes both keys with the expected payload and TTL."""

    user = _user_like(42, "a@x.com", ["user"])
    ttl = 86400

    session_id = await sessions.create(user, redis=redis, ttl_seconds=ttl)

    # 64 hex chars, all [0-9a-f].
    assert isinstance(session_id, str)
    assert len(session_id) == 64
    assert all(c in "0123456789abcdef" for c in session_id)

    raw = await redis.get(f"session:{session_id}")
    assert raw is not None
    payload = json.loads(raw)
    assert payload["user_id"] == 42
    assert payload["email"] == "a@x.com"
    assert payload["roles"] == ["user"]
    assert "created_at" in payload

    members = await redis.smembers("user_sessions:42")
    assert session_id in members

    session_ttl = await redis.ttl(f"session:{session_id}")
    reverse_ttl = await redis.ttl("user_sessions:42")
    assert 0 < session_ttl <= ttl
    assert 0 < reverse_ttl <= ttl
    # Both keys are expected to hit within a couple of seconds of ttl
    # unless the CI box is pathologically slow.
    assert session_ttl >= ttl - 5
    assert reverse_ttl >= ttl - 5


async def test_get_returns_auth_context(redis):
    """Case 2: get returns an AuthContext that mirrors the payload."""

    user = _user_like(42, "a@x.com", ["user"])
    session_id = await sessions.create(user, redis=redis, ttl_seconds=600)

    ctx = await sessions.get(session_id, redis=redis)

    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == 42
    assert ctx.email == "a@x.com"
    assert ctx.roles == ("user",)
    assert ctx.session_id == session_id


async def test_get_missing_key_returns_none(redis):
    """Case 3: a random session ID resolves to None."""

    ctx = await sessions.get("a" * 64, redis=redis)
    assert ctx is None


async def test_get_malformed_payload_returns_none(redis):
    """Case 4: non-JSON in the session key does not raise."""

    session_id = "f" * 64
    await redis.set(f"session:{session_id}", "not json")
    ctx = await sessions.get(session_id, redis=redis)
    assert ctx is None


async def test_delete_wipes_both_keys(redis):
    """Case 5: delete removes the session and reverse-index entry."""

    user = _user_like(42, "a@x.com", ["user"])
    session_id = await sessions.create(user, redis=redis, ttl_seconds=600)

    await sessions.delete(session_id, 42, redis=redis)

    raw = await redis.get(f"session:{session_id}")
    assert raw is None

    members = await redis.smembers("user_sessions:42")
    assert session_id not in members


async def test_revoke_all_for_user_drops_every_session(redis):
    """Case 6: revoke_all_for_user wipes every session for a user."""

    user = _user_like(42, "a@x.com", ["user"])
    sid_a = await sessions.create(user, redis=redis, ttl_seconds=600)
    sid_b = await sessions.create(user, redis=redis, ttl_seconds=600)

    assert sid_a != sid_b

    await sessions.revoke_all_for_user(42, redis=redis)

    assert await redis.get(f"session:{sid_a}") is None
    assert await redis.get(f"session:{sid_b}") is None
    # Reverse index gone too.
    assert await redis.exists("user_sessions:42") == 0


async def test_revoke_all_for_user_noop_when_empty(redis):
    """Case 7: calling revoke on a user with no sessions is a no-op."""

    # Never-logged-in user ID; no arrangement.
    await sessions.revoke_all_for_user(999_999, redis=redis)
    # Nothing to assert except "did not raise"; sanity-check the key.
    assert await redis.exists("user_sessions:999999") == 0


async def test_ttl_is_exactly_session_ttl_seconds(redis):
    """Case 8: TTL matches the configured value at creation time."""

    user = _user_like(42, "a@x.com", ["user"])
    await sessions.create(user, redis=redis, ttl_seconds=10)

    members = await redis.smembers("user_sessions:42")
    sid = next(iter(members))

    session_ttl = await redis.ttl(f"session:{sid}")
    reverse_ttl = await redis.ttl("user_sessions:42")

    assert 8 <= session_ttl <= 10
    assert 8 <= reverse_ttl <= 10
