"""Shared pytest fixtures for the external REST functional test suite.

The suite connects to a running minimalist-app compose stack via HTTP only.
It imports nothing from ``backend/`` — this is deliberate. See
``docs/specs/feat_testing_001/design_testing_001.md`` for the rationale.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest


DEFAULT_BASE_URL = "http://localhost:8000"
CLIENT_TIMEOUT = 10.0


@pytest.fixture(scope="session")
def base_url() -> str:
    """Return the backend base URL, configurable via ``TEST_BASE_URL``."""

    return os.environ.get("TEST_BASE_URL", DEFAULT_BASE_URL)


@pytest.fixture(scope="session")
def client(base_url: str) -> Iterator[httpx.Client]:
    """Yield a session-scoped :class:`httpx.Client` bound to ``base_url``."""

    with httpx.Client(base_url=base_url, timeout=CLIENT_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def readiness_check(base_url: str) -> None:
    """Fail fast with a readable message if the stack is not reachable.

    ``test.sh`` already waits for ``/readyz`` before invoking pytest, but a
    developer running ``uv run pytest`` directly skips that gate; this fixture
    gives them the same friendly diagnostic.
    """

    try:
        response = httpx.get(f"{base_url}/readyz", timeout=5.0)
    except httpx.HTTPError as exc:
        raise pytest.UsageError(
            f"stack not reachable at {base_url}; "
            "did you run ./test.sh or `make up`? "
            f"(underlying error: {exc!r})"
        ) from exc

    if response.status_code != 200:
        raise pytest.UsageError(
            f"stack at {base_url} returned {response.status_code} from /readyz; "
            "did you run ./test.sh or `make up`?"
        )
