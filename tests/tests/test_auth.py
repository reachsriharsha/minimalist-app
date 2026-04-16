"""Black-box checks for ``/api/v1/auth/me`` and ``/api/v1/auth/logout``.

External REST suite — runs against the compose-brought-up backend. The
default dev compose runs with ``ENV=dev`` which does **not** mount the
test-only mint endpoint, so these tests only cover the unauthenticated
code path (401 / cookie-not-set paths).
"""

from __future__ import annotations

import httpx


ME_PATH = "/api/v1/auth/me"
LOGOUT_PATH = "/api/v1/auth/logout"


def test_auth_me_requires_a_cookie(client: httpx.Client) -> None:
    """Without a session cookie ``/auth/me`` returns 401."""

    response = client.get(ME_PATH)

    assert response.status_code == 401, response.text
    body = response.json()
    assert "error" in body
    # Error envelope carries ``message`` and ``request_id`` fields; we
    # only assert the message because envelope shape is
    # feat_backend_002's contract.
    assert body["error"]["message"] == "not_authenticated"


def test_auth_logout_requires_a_cookie(client: httpx.Client) -> None:
    """Without a session cookie ``/auth/logout`` returns 401."""

    response = client.post(LOGOUT_PATH)

    assert response.status_code == 401, response.text
    body = response.json()
    assert body["error"]["message"] == "not_authenticated"
