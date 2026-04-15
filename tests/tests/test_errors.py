"""Black-box check for the 404 error envelope shape.

Asserts the keys and types of the documented envelope, not the specific
``code`` or ``message`` strings — those are backend-owned and may evolve
without breaking the external contract.
"""

from __future__ import annotations

import httpx


def test_unknown_path_returns_error_envelope(client: httpx.Client) -> None:
    """An unknown path returns 404 with ``{"error": {code, message, request_id}}``."""

    response = client.get("/__does_not_exist__")

    assert response.status_code == 404, response.text
    body = response.json()

    assert isinstance(body, dict), body
    assert "error" in body, body

    error = body["error"]
    assert isinstance(error, dict), error
    assert set(error.keys()) >= {"code", "message", "request_id"}, error

    assert isinstance(error["code"], str) and error["code"], error
    assert isinstance(error["message"], str) and error["message"], error
    # ``request_id`` may be empty string if the server somehow could not bind
    # one, but the key must be present and the value a string.
    assert isinstance(error["request_id"], str), error
