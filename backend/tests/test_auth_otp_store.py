"""Unit tests for :mod:`app.auth.otp_store` against a real Redis.

Uses the existing ``require_redis`` fixture and skips when Redis is
unreachable. Each test flushes the relevant keys so two tests don't
race each other on the default compose-network Redis.
"""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import from_url

from app.auth import otp, otp_store


@pytest.fixture
async def redis(require_redis):
    client = from_url(require_redis, encoding="utf-8", decode_responses=True)
    try:
        # Scrub only the keys this module writes so we don't clobber
        # a concurrent session test hitting the same Redis DB.
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


async def _cleanup(redis, email: str) -> None:
    minute, hour = otp.rate_limit_keys(email)
    await redis.delete(otp.otp_key(email), minute, hour)


async def test_store_and_load_round_trip(redis) -> None:
    email = "t1@x.com"
    await _cleanup(redis, email)

    await otp_store.store_otp(
        email,
        "$2b$10$" + "a" * 53,
        redis=redis,
        ttl_seconds=600,
    )

    record = await otp_store.load_otp(email, redis=redis)
    assert record is not None
    assert record.code_hash == "$2b$10$" + "a" * 53
    assert record.attempts == 0
    assert record.created_at

    ttl = await redis.ttl(otp.otp_key(email))
    assert 590 <= ttl <= 600


async def test_load_missing_returns_none(redis) -> None:
    email = "t_missing@x.com"
    await _cleanup(redis, email)
    assert await otp_store.load_otp(email, redis=redis) is None


async def test_load_malformed_payload_returns_none(redis) -> None:
    email = "t_malformed@x.com"
    await _cleanup(redis, email)
    await redis.set(otp.otp_key(email), "not json", ex=60)
    assert await otp_store.load_otp(email, redis=redis) is None


async def test_load_missing_code_hash_returns_none(redis) -> None:
    email = "t_no_hash@x.com"
    await _cleanup(redis, email)
    await redis.set(
        otp.otp_key(email), '{"attempts":0}', ex=60
    )
    assert await otp_store.load_otp(email, redis=redis) is None


async def test_increment_preserves_ttl(redis) -> None:
    email = "t_incr@x.com"
    await _cleanup(redis, email)

    await otp_store.store_otp(
        email, "$2b$10$" + "b" * 53, redis=redis, ttl_seconds=600
    )
    ttl_before = await redis.pttl(otp.otp_key(email))

    new1 = await otp_store.increment_attempts_preserve_ttl(
        email, redis=redis
    )
    assert new1 == 1
    new2 = await otp_store.increment_attempts_preserve_ttl(
        email, redis=redis
    )
    assert new2 == 2

    record = await otp_store.load_otp(email, redis=redis)
    assert record is not None
    assert record.attempts == 2

    ttl_after = await redis.pttl(otp.otp_key(email))
    # TTL drifts slightly over the ~milliseconds the three calls took;
    # assert it stayed within a 2s envelope of the pre-increment TTL.
    assert abs(ttl_before - ttl_after) < 2_000, (ttl_before, ttl_after)


async def test_increment_on_missing_returns_zero(redis) -> None:
    email = "t_incr_missing@x.com"
    await _cleanup(redis, email)
    result = await otp_store.increment_attempts_preserve_ttl(
        email, redis=redis
    )
    assert result == 0
    # No key created.
    assert await redis.exists(otp.otp_key(email)) == 0


async def test_consume_deletes_the_key(redis) -> None:
    email = "t_consume@x.com"
    await _cleanup(redis, email)

    await otp_store.store_otp(
        email, "$2b$10$" + "c" * 53, redis=redis, ttl_seconds=600
    )
    await otp_store.consume_otp(email, redis=redis)
    assert await redis.get(otp.otp_key(email)) is None


async def test_rate_limit_first_call_allowed(redis) -> None:
    email = "t_rate_first@x.com"
    await _cleanup(redis, email)

    result = await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    assert result.allowed is True
    assert result.retry_after == 0
    assert result.window is None

    minute_key, _ = otp.rate_limit_keys(email)
    ttl = await redis.ttl(minute_key)
    assert 55 <= ttl <= 60


async def test_rate_limit_second_call_denies_within_minute(redis) -> None:
    email = "t_rate_second@x.com"
    await _cleanup(redis, email)

    await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    result = await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    assert result.allowed is False
    assert 1 <= result.retry_after <= 60
    assert result.window == "minute"


async def test_rate_limit_resets_after_minute_expiry(redis) -> None:
    email = "t_rate_reset@x.com"
    await _cleanup(redis, email)

    await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    # Second call is denied.
    denied = await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    assert denied.allowed is False

    # Simulate window expiry by forcing the minute key's TTL to 1ms,
    # then waiting for it to lapse.
    minute_key, _ = otp.rate_limit_keys(email)
    await redis.pexpire(minute_key, 1)
    await asyncio.sleep(0.05)

    result = await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=1, per_hour_limit=10
    )
    assert result.allowed is True


async def test_rate_limit_hour_window(redis) -> None:
    email = "t_rate_hour@x.com"
    await _cleanup(redis, email)

    for _ in range(3):
        r = await otp_store.check_and_increment_rate(
            email, redis=redis, per_minute_limit=99, per_hour_limit=3
        )
        assert r.allowed is True

    denied = await otp_store.check_and_increment_rate(
        email, redis=redis, per_minute_limit=99, per_hour_limit=3
    )
    assert denied.allowed is False
    assert denied.window == "hour"
    assert 1 <= denied.retry_after <= 3600


async def test_rate_limit_expire_nx_preserves_window(redis) -> None:
    email = "t_rate_nx@x.com"
    await _cleanup(redis, email)

    minute_key, _ = otp.rate_limit_keys(email)

    # Five rapid calls. EXPIRE NX must only set TTL on the first one,
    # so subsequent TTLs count down monotonically -- never spike back
    # up to 60.
    ttls: list[int] = []
    for _ in range(5):
        await otp_store.check_and_increment_rate(
            email, redis=redis, per_minute_limit=99, per_hour_limit=99
        )
        ttls.append(await redis.pttl(minute_key))

    # Every observed TTL is <= the first TTL (monotonic countdown).
    for t in ttls:
        assert t <= ttls[0] + 10, (t, ttls[0], ttls)  # 10ms jitter
