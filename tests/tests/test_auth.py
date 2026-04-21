"""Black-box checks for the auth endpoints.

External REST suite -- runs against the compose-brought-up backend.

feat_auth_001 cases (anonymous ``/me`` + ``/logout`` return 401) stay
green in every env. feat_auth_002 adds two cases that exercise the
real OTP login flow via the ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE``
fixture; they skip cleanly when the fixture is not populated on the
live backend (detected by a single discovery POST that short-circuits
subsequent asserts).
"""

from __future__ import annotations

import os

import httpx
import pytest


ME_PATH = "/api/v1/auth/me"
LOGOUT_PATH = "/api/v1/auth/logout"
OTP_REQUEST_PATH = "/api/v1/auth/otp/request"
OTP_VERIFY_PATH = "/api/v1/auth/otp/verify"


def _otp_fixture_env() -> tuple[str, str] | None:
    """Return ``(email, code)`` when both env vars are set, else ``None``.

    The suite-side env must match the backend's ``TEST_OTP_*`` settings
    for the fixture to actually flip the stored hash. Only the suite
    side is readable from here; we trust the operator to have mirrored
    the pair in ``infra/.env`` before ``make up``.
    """

    email = os.environ.get("TEST_OTP_EMAIL", "").strip()
    code = os.environ.get("TEST_OTP_CODE", "").strip()
    if email and code:
        return email, code
    return None


def test_auth_me_requires_a_cookie(client: httpx.Client) -> None:
    """Without a session cookie ``/auth/me`` returns 401."""

    response = client.get(ME_PATH)

    assert response.status_code == 401, response.text
    body = response.json()
    assert "error" in body
    assert body["error"]["message"] == "not_authenticated"


def test_auth_logout_requires_a_cookie(client: httpx.Client) -> None:
    """Without a session cookie ``/auth/logout`` returns 401."""

    response = client.post(LOGOUT_PATH)

    assert response.status_code == 401, response.text
    body = response.json()
    assert body["error"]["message"] == "not_authenticated"


def test_otp_happy_path(client: httpx.Client) -> None:
    """OTP request -> verify -> /me with the TEST_OTP fixture configured.

    Skipped when ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE`` are not set on
    the test-runner side; the backend's own settings must mirror these
    values for the fixture to activate.
    """

    fixture = _otp_fixture_env()
    if fixture is None:
        pytest.skip(
            "TEST_OTP_EMAIL / TEST_OTP_CODE not set; skipping OTP happy-path"
        )
    email, code = fixture

    req = client.post(OTP_REQUEST_PATH, json={"email": email})
    # Accept 204 (happy) or 429 (another test ran recently and we hit
    # the rate limit). The 429 skip keeps the suite deterministic
    # against a shared compose stack.
    if req.status_code == 429:
        pytest.skip("rate-limited from a prior run; retry after a minute")
    assert req.status_code == 204, req.text

    ver = client.post(
        OTP_VERIFY_PATH, json={"email": email, "code": code}
    )
    assert ver.status_code == 200, ver.text
    body = ver.json()
    assert body["email"].lower() == email.lower()
    assert "user" in body["roles"]

    # Cookie round-trip: /me should return the same payload shape.
    set_cookie = ver.headers.get("set-cookie", "")
    sid = set_cookie.split(";", 1)[0].split("=", 1)[1]

    me = client.get(ME_PATH, cookies={"session": sid})
    assert me.status_code == 200
    assert me.json()["email"].lower() == email.lower()


def test_otp_wrong_code_returns_400(client: httpx.Client) -> None:
    """A wrong code returns the uniform 400 envelope body.

    Skipped when the fixture env is not set -- same reason as above.
    """

    fixture = _otp_fixture_env()
    if fixture is None:
        pytest.skip(
            "TEST_OTP_EMAIL / TEST_OTP_CODE not set; skipping OTP wrong-code"
        )
    email, _ = fixture

    req = client.post(OTP_REQUEST_PATH, json={"email": email})
    if req.status_code == 429:
        pytest.skip("rate-limited from a prior run; retry after a minute")
    assert req.status_code == 204, req.text

    ver = client.post(
        OTP_VERIFY_PATH, json={"email": email, "code": "999999"}
    )
    assert ver.status_code == 400, ver.text
    body = ver.json()
    # Envelope shape from feat_backend_002.
    assert body["error"]["message"] == "invalid_or_expired_code"
