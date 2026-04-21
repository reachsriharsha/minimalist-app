"""Unit tests for the pure helpers in :mod:`app.auth.otp`.

No Redis, no Postgres, no event loop required. Runs in every CI
configuration including a bare clone with no containers.
"""

from __future__ import annotations

import inspect
import re
import time

import pytest

from app.auth import otp


def test_generate_code_always_six_digits() -> None:
    for _ in range(10_000):
        code = otp.generate_code()
        assert re.match(r"^[0-9]{6}$", code), code


def test_generate_code_uses_secrets_not_random() -> None:
    source = inspect.getsource(otp.generate_code)
    assert "secrets.randbelow" in source
    # Confirm ``random`` is not a top-level import either. Docstrings
    # are allowed to mention ``random.randrange`` in comparative
    # context; an actual import is what would matter.
    import ast as _ast

    tree = _ast.parse(inspect.getsource(otp))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert alias.name != "random", alias.name
        elif isinstance(node, _ast.ImportFrom):
            assert node.module != "random", node.module


def test_hash_and_verify_round_trip() -> None:
    code = "123456"
    assert otp.verify_code(code, otp.hash_code(code)) is True


def test_verify_mismatch_returns_false() -> None:
    assert otp.verify_code("000000", otp.hash_code("123456")) is False


def test_verify_malformed_hash_returns_false() -> None:
    assert otp.verify_code("123456", "not-a-bcrypt-hash") is False


def test_verify_constant_time_smoke() -> None:
    """Smoke check: correct and wrong verifies finish in the same ballpark.

    This is *not* a proof of constant-time execution; bcrypt's cost
    dominates both paths. Assert only that neither batch is wildly
    outside the other (generous ratio bound for shared CI hosts
    where bcrypt runtime varies with load).
    """

    h = otp.hash_code("123456")

    def _bench(code: str, hash_: str) -> float:
        start = time.perf_counter()
        for _ in range(50):
            otp.verify_code(code, hash_)
        return time.perf_counter() - start

    a = _bench("123456", h)
    b = _bench("999999", h)
    # Ratio bound instead of an absolute one -- bcrypt 50x at factor
    # 10 ranges from ~500ms to ~15s depending on host. Assert neither
    # side is more than 40% slower than the other.
    lo, hi = min(a, b), max(a, b)
    assert hi / lo < 1.4, (a, b)


@pytest.mark.parametrize(
    "inputs",
    [
        ["Alice@X.com", " alice@x.com ", "alice@x.com", "ALICE@X.COM"],
    ],
)
def test_email_hash_lowercases_and_trims(inputs: list[str]) -> None:
    first = otp.email_hash(inputs[0])
    for other in inputs[1:]:
        assert otp.email_hash(other) == first


def test_email_hash_output_shape() -> None:
    result = otp.email_hash("anything@example.com")
    assert re.match(r"^[0-9a-f]{64}$", result)


def test_otp_key_shape() -> None:
    assert otp.otp_key("alice@x.com") == f"otp:{otp.email_hash('alice@x.com')}"


def test_rate_limit_keys_shape() -> None:
    minute, hour = otp.rate_limit_keys("alice@x.com")
    h = otp.email_hash("alice@x.com")
    assert minute == f"otp_rate:{h}:minute"
    assert hour == f"otp_rate:{h}:hour"


def test_bcrypt_work_factor_is_10_rounds() -> None:
    h = otp.hash_code("000000")
    # bcrypt hash shape: ``$2b$<rounds>$<salt+hash>``.
    assert h.startswith("$2b$10$"), h
