"""Pure helpers for the OTP flow.

Deterministic, no I/O. Every Redis-touching helper lives in
:mod:`app.auth.otp_store`; this module is safe to import from anywhere
without pulling Redis client construction into the call graph.

Design references:

- ``docs/design/auth-login-and-roles.md`` §6.2 — Redis keyspace
  (``otp:<h>``, ``otp_rate:<h>:minute``, ``otp_rate:<h>:hour``).
- ``docs/specs/feat_auth_002/feat_auth_002.md`` requirement 5 — helper
  names, bcrypt work factor (10 rounds), six-digit format.

Notes:

- ``email_hash`` is used verbatim as the last segment of every Redis key
  the flow writes. It lowercases + strips before hashing so the same
  user cannot cause two independent buckets by sending two different
  cases of the same email.
- ``generate_code`` uses :func:`secrets.randbelow` (not
  :func:`random.randrange`) per design-doc §8 ("cryptographic RNG for
  all OTP codes").
- ``hash_code`` pins the bcrypt work factor at **10 rounds**. Higher
  factors buy nothing against the 1M-entry search space; see the feature
  spec for the rationale.
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt

# Pinned work factor. Tested via ``test_auth_otp_helpers.py`` case 10 by
# checking the ``$2b$10$`` prefix on a sample hash.
_BCRYPT_ROUNDS = 10

# Namespace prefixes. Defined once here so callers never hand-string a
# key; matches the pattern :mod:`app.auth.sessions` already uses.
_OTP_KEY_PREFIX = "otp:"
_OTP_RATE_MINUTE_SUFFIX = ":minute"
_OTP_RATE_HOUR_SUFFIX = ":hour"
_OTP_RATE_PREFIX = "otp_rate:"


def email_hash(email: str) -> str:
    """Return the SHA-256 hex digest of the normalized email.

    Normalization is ``.strip().lower()`` so inputs differing only in
    whitespace or case produce the same key, matching the ``CITEXT``
    semantics on ``users.email``.
    """

    normalized = (email or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_code() -> str:
    """Return a fresh six-digit OTP code as a zero-padded string.

    Draws uniformly from ``[0, 10**6)`` via :func:`secrets.randbelow`,
    then zero-pads to width 6 so ``"012345"`` is preserved verbatim
    (bcrypt input is byte-sensitive).
    """

    return f"{secrets.randbelow(10**6):06d}"


def hash_code(code: str) -> str:
    """Return the bcrypt hash of ``code`` at the pinned work factor."""

    return bcrypt.hashpw(
        code.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_code(code: str, hash_: str) -> bool:
    """Constant-time compare between ``code`` and ``hash_``.

    Wraps :func:`bcrypt.checkpw`. Returns ``False`` on any malformed
    hash rather than raising, because the verify handler treats every
    bad-code condition as the same 400 and there is no caller that
    wants to distinguish "hash is garbled" from "code does not match".
    """

    try:
        return bcrypt.checkpw(code.encode("utf-8"), hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def otp_key(email: str) -> str:
    """Return the ``otp:<h>`` Redis key for ``email``."""

    return f"{_OTP_KEY_PREFIX}{email_hash(email)}"


def rate_limit_keys(email: str) -> tuple[str, str]:
    """Return ``(minute_key, hour_key)`` for ``email``.

    The minute key precedes the hour key in the returned tuple because
    the minute window is the first-to-deny on a burst, and the caller
    (``check_and_increment_rate``) uses that order when filling out
    ``RateLimitResult.window``.
    """

    h = email_hash(email)
    return (
        f"{_OTP_RATE_PREFIX}{h}{_OTP_RATE_MINUTE_SUFFIX}",
        f"{_OTP_RATE_PREFIX}{h}{_OTP_RATE_HOUR_SUFFIX}",
    )


__all__ = [
    "email_hash",
    "generate_code",
    "hash_code",
    "verify_code",
    "otp_key",
    "rate_limit_keys",
]
