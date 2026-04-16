"""Redis-backed session store.

Design references: §6.2 (keyspaces) and §7.4 / §7.5 / §7.6 of
``docs/design/auth-login-and-roles.md``, plus the "Data flow" section of
``docs/specs/feat_auth_001/design_auth_001.md``.

Key shapes:

- ``session:<64-hex>`` — JSON payload describing the authenticated user.
  TTL = ``settings.session_ttl_seconds``.
- ``user_sessions:<user_id>`` — Redis ``SET`` of session IDs owned by
  the user, used as a reverse index for ``revoke_all_for_user``.

Only two helpers in this feature ever touch Redis: :func:`create` writes
both keys, :func:`delete` and :func:`revoke_all_for_user` tear them down.
The middleware uses :func:`get` to resolve a cookie into an
:class:`AuthContext`.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable

from redis.asyncio import Redis

from app.auth.schemas import AuthContext

# Exposed as module-level constants so call sites never hand-string Redis
# keys. Keeps future "rename the key" refactors one-edit jobs.
SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_KEY_PREFIX = "user_sessions:"


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _user_sessions_key(user_id: int | str) -> str:
    return f"{USER_SESSIONS_KEY_PREFIX}{user_id}"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat()


def _decode_member(value: bytes | str) -> str:
    """Normalize a Redis ``SMEMBERS`` element to ``str``.

    The repo default builds the async Redis client with
    ``decode_responses=True`` so members arrive as ``str`` already, but
    callers may hand us a raw bytes-mode client; support both.
    """

    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


async def create(
    user: Any,
    *,
    redis: Redis,
    ttl_seconds: int,
) -> str:
    """Mint a new session for ``user`` and return its opaque ID.

    ``user`` is any object with ``id``, ``email``, and a ``roles``
    iterable whose elements expose a ``name`` attribute. Typically a
    :class:`app.auth.models.User`, but the test suite passes a lightweight
    stand-in, so the contract is kept duck-typed.

    Writes both the session payload and the reverse-index entry in a
    single pipelined round-trip.
    """

    session_id = secrets.token_hex(32)  # 64 hex chars, 256 bits of entropy
    payload = {
        "user_id": int(user.id),
        "email": str(user.email),
        "roles": [r.name for r in user.roles],
        "created_at": _now_iso(),
    }

    session_key = _session_key(session_id)
    reverse_key = _user_sessions_key(user.id)

    pipe = redis.pipeline()
    pipe.set(session_key, json.dumps(payload), ex=ttl_seconds)
    pipe.sadd(reverse_key, session_id)
    pipe.expire(reverse_key, ttl_seconds)
    await pipe.execute()

    return session_id


async def get(session_id: str, *, redis: Redis) -> AuthContext | None:
    """Resolve a session ID to an :class:`AuthContext` or ``None``.

    Collapses three failure modes — missing key, malformed JSON, missing
    required field — to ``None``. The middleware treats ``None`` as
    "anonymous" and clears the cookie; no exception escapes.
    """

    raw = await redis.get(_session_key(session_id))
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

    try:
        user_id = int(payload["user_id"])
        email = str(payload["email"])
        roles = tuple(str(r) for r in payload.get("roles", []))
    except (KeyError, TypeError, ValueError):
        return None

    return AuthContext(
        user_id=user_id,
        email=email,
        roles=roles,
        session_id=session_id,
    )


async def delete(
    session_id: str,
    user_id: int,
    *,
    redis: Redis,
) -> None:
    """Remove a single session and its reverse-index membership.

    Safe to call for a session that has already expired in Redis — both
    ``DEL`` and ``SREM`` are idempotent and happily return 0 when the
    target is absent.
    """

    pipe = redis.pipeline()
    pipe.delete(_session_key(session_id))
    pipe.srem(_user_sessions_key(user_id), session_id)
    await pipe.execute()


async def revoke_all_for_user(
    user_id: int,
    *,
    redis: Redis,
) -> None:
    """Wipe every active session for ``user_id``.

    Fetches the reverse-index set, deletes every referenced session key
    in one ``DELETE`` call, then drops the reverse index itself. No-op
    when the reverse index is empty.
    """

    members: Iterable[bytes | str] = await redis.smembers(
        _user_sessions_key(user_id)
    )
    session_ids = [_decode_member(m) for m in members]
    if session_ids:
        await redis.delete(*[_session_key(sid) for sid in session_ids])
    await redis.delete(_user_sessions_key(user_id))


__all__ = [
    "SESSION_KEY_PREFIX",
    "USER_SESSIONS_KEY_PREFIX",
    "create",
    "get",
    "delete",
    "revoke_all_for_user",
]
