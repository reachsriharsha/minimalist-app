"""Redis-backed storage for OTP codes and rate-limit counters.

Design references:

- ``docs/design/auth-login-and-roles.md`` §6.2 (keyspace) and §7.1
  (request/verify data flow).
- ``docs/specs/feat_auth_002/feat_auth_002.md`` requirement 6.
- ``docs/specs/feat_auth_002/design_auth_002.md`` — data-flow diagrams
  + the Lua snippet for ``increment_attempts_preserve_ttl``.

Contract:

- ``OtpRecord`` and ``RateLimitResult`` are tiny frozen dataclasses.
  No Pydantic -- these are internal value objects, never serialized to
  the wire (the router crafts its own response bodies).
- Every helper takes ``redis: Redis`` as a keyword argument. None of
  them construct a client.
- Missing, malformed, or expired keys collapse to ``None`` / returns
  the ``allowed=True`` branch where appropriate -- the verify handler
  uses these collapses to produce the uniform
  ``invalid_or_expired_code`` response.
- ``increment_attempts_preserve_ttl`` is implemented via a server-side
  Lua script (Redis ``EVAL``) so the read-modify-write is atomic and
  the remaining PTTL is preserved without relying on Redis 7's
  ``KEEPTTL`` option.

Logging: this module does **not** emit log events. The router is the
single source of observability events for the OTP flow (requirement 15
of the feature spec).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from redis.asyncio import Redis

from app.auth import otp


@dataclass(frozen=True, slots=True)
class OtpRecord:
    """Deserialized value stored under ``otp:<h>``.

    ``created_at`` is carried so operators can reason about how far
    into the TTL a given verify attempt lands; the router does not
    act on it.
    """

    code_hash: str
    attempts: int
    created_at: str


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of :func:`check_and_increment_rate`.

    ``window`` names the offending bucket so the caller can log a
    descriptive event; it is ``None`` when the call was allowed.
    """

    allowed: bool
    retry_after: int
    window: Literal["minute", "hour"] | None = None


# ---------------------------------------------------------------------------
# OTP record helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_record(code_hash: str, attempts: int, created_at: str) -> str:
    return json.dumps(
        {
            "code_hash": code_hash,
            "attempts": attempts,
            "created_at": created_at,
        }
    )


async def store_otp(
    email: str,
    code_hash: str,
    *,
    redis: Redis,
    ttl_seconds: int,
) -> None:
    """Store a fresh OTP record for ``email`` with ``attempts=0``.

    Overwrites any existing record. TTL is reset to ``ttl_seconds`` on
    every call -- the test-OTP fixture relies on this for its
    "regenerate the stored hash" flow.
    """

    key = otp.otp_key(email)
    value = _encode_record(code_hash, 0, _now_iso())
    await redis.set(key, value, ex=ttl_seconds)


async def load_otp(email: str, *, redis: Redis) -> OtpRecord | None:
    """Return the stored :class:`OtpRecord` or ``None``.

    ``None`` covers: missing key, non-JSON payload, JSON payload that
    isn't a dict, and payload missing ``code_hash``. The verify handler
    treats each of those as "invalid or expired code" -- collapsing
    them here keeps the handler branch-free on the read path.
    """

    key = otp.otp_key(email)
    raw = await redis.get(key)
    if raw is None:
        return None

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    code_hash = payload.get("code_hash")
    if not isinstance(code_hash, str) or not code_hash:
        return None

    attempts_raw = payload.get("attempts", 0)
    try:
        attempts = int(attempts_raw)
    except (TypeError, ValueError):
        attempts = 0

    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        created_at = ""

    return OtpRecord(
        code_hash=code_hash,
        attempts=attempts,
        created_at=created_at,
    )


# Lua script: atomically re-write the JSON value at KEYS[1] with
# ``attempts`` incremented, preserving the remaining PTTL. Returns the
# new attempts count, or 0 when the key is missing/malformed (caller
# treats that as "nothing to do").
#
# Why Lua (server-side) and not Python read-modify-write: the verify
# handler is concurrent across multiple workers. A Python-side GET/SET
# loop would race two wrong-code attempts into a single ``attempts=1``
# state and lose the second increment. The server-side Lua script runs
# atomically inside Redis.
_INCREMENT_ATTEMPTS_LUA = """
local raw = redis.call('GET', KEYS[1])
if raw == false then return 0 end
local ok, obj = pcall(cjson.decode, raw)
if not ok or type(obj) ~= 'table' then return 0 end
local attempts = tonumber(obj.attempts) or 0
attempts = attempts + 1
obj.attempts = attempts
local ttl = redis.call('PTTL', KEYS[1])
if ttl == nil or ttl <= 0 then return 0 end
redis.call('SET', KEYS[1], cjson.encode(obj), 'PX', ttl)
return attempts
"""


async def increment_attempts_preserve_ttl(
    email: str, *, redis: Redis
) -> int:
    """Increment ``attempts`` atomically and return the new count.

    Preserves the remaining PTTL of the key exactly. Returns ``0`` when
    the key is missing or malformed -- the verify handler has already
    produced its response at that point, so the return value is
    informational.
    """

    key = otp.otp_key(email)
    # redis-py exposes the EVAL command as ``redis.eval`` (Lua script
    # execution on the server; unrelated to Python's builtin).
    result = await redis.eval(_INCREMENT_ATTEMPTS_LUA, 1, key)  # noqa: S307
    try:
        return int(result)
    except (TypeError, ValueError):
        return 0


async def consume_otp(email: str, *, redis: Redis) -> None:
    """Delete the OTP record for ``email`` (one-shot on success)."""

    await redis.delete(otp.otp_key(email))


# ---------------------------------------------------------------------------
# Rate-limit helpers
# ---------------------------------------------------------------------------


async def check_and_increment_rate(
    email: str,
    *,
    redis: Redis,
    per_minute_limit: int,
    per_hour_limit: int,
) -> RateLimitResult:
    """Consume one unit from the minute + hour rate-limit buckets.

    Pipelined: ``INCR minute, EXPIRE minute 60 NX, INCR hour,
    EXPIRE hour 3600 NX``. Four commands, one round-trip.

    ``EXPIRE ... NX`` means "set the TTL only if no TTL exists" -- so
    the 60-second window starts at the *first* request, not the most
    recent. Subsequent increments observe the TTL counting down
    monotonically.

    Return value:

    - ``allowed=True`` when both counters are within their respective
      limits. ``retry_after=0``, ``window=None``.
    - ``allowed=False`` when either counter exceeds its limit. The
      minute window takes precedence when both are full (it unblocks
      sooner). ``retry_after`` is the remaining TTL in seconds of the
      offending key, rounded up to at least 1.
    """

    minute_key, hour_key = otp.rate_limit_keys(email)

    pipe = redis.pipeline()
    pipe.incr(minute_key)
    pipe.expire(minute_key, 60, nx=True)
    pipe.incr(hour_key)
    pipe.expire(hour_key, 3600, nx=True)
    minute_count, _m_expire, hour_count, _h_expire = await pipe.execute()

    try:
        minute_count = int(minute_count)
        hour_count = int(hour_count)
    except (TypeError, ValueError):
        # Pathological: Redis returned something un-int-able. Fail open.
        return RateLimitResult(allowed=True, retry_after=0, window=None)

    minute_over = minute_count > per_minute_limit
    hour_over = hour_count > per_hour_limit
    if not minute_over and not hour_over:
        return RateLimitResult(allowed=True, retry_after=0, window=None)

    # Prefer the minute window when both are full -- it expires sooner,
    # so the user sees a more useful ``retry_after``.
    offending_key = minute_key if minute_over else hour_key
    window: Literal["minute", "hour"] = "minute" if minute_over else "hour"

    ttl_seconds = await redis.ttl(offending_key)
    try:
        ttl_int = int(ttl_seconds)
    except (TypeError, ValueError):
        ttl_int = -1
    if ttl_int < 0:
        # ``-2``: key missing (shouldn't happen right after INCR).
        # ``-1``: key exists with no TTL (EXPIRE NX lost a race with
        # a previous call that had a TTL drop). Either way, report a
        # conservative 1-second retry so the caller still denies.
        ttl_int = 1
    retry_after = max(1, ttl_int)

    return RateLimitResult(
        allowed=False,
        retry_after=retry_after,
        window=window,
    )


__all__ = [
    "OtpRecord",
    "RateLimitResult",
    "store_otp",
    "load_otp",
    "increment_attempts_preserve_ttl",
    "consume_otp",
    "check_and_increment_rate",
]
