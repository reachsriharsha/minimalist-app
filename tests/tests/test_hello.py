"""Black-box checks for ``GET /api/v1/hello``."""

from __future__ import annotations

import httpx


HELLO_PATH = "/api/v1/hello"


def test_hello_shape(client: httpx.Client) -> None:
    """Response must match ``{message: str, item_name: str, hello_count: int}``."""

    response = client.get(HELLO_PATH)

    assert response.status_code == 200, response.text
    body = response.json()

    assert isinstance(body, dict), body
    assert set(body.keys()) >= {"message", "item_name", "hello_count"}, body

    assert isinstance(body["message"], str) and body["message"], body
    assert isinstance(body["item_name"], str) and body["item_name"], body
    # ``bool`` is a subclass of ``int`` in Python; exclude it explicitly so a
    # regression that returns ``True``/``False`` would be caught.
    assert isinstance(body["hello_count"], int), body
    assert not isinstance(body["hello_count"], bool), body


def test_hello_count_increments_by_one(client: httpx.Client) -> None:
    """Two consecutive calls must increase ``hello_count`` by exactly 1.

    This is a *relative* assertion — it does not depend on the absolute
    starting value, so it is correct on a fresh stack, on a re-run, and on
    a stack that has served other traffic.
    """

    first = client.get(HELLO_PATH)
    second = client.get(HELLO_PATH)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_count = first.json()["hello_count"]
    second_count = second.json()["hello_count"]

    assert isinstance(first_count, int) and not isinstance(first_count, bool)
    assert isinstance(second_count, int) and not isinstance(second_count, bool)
    assert second_count == first_count + 1, (first_count, second_count)
