"""Unit tests for the two concrete :class:`EmailSender` implementations.

``ResendEmailSender`` is exercised via ``httpx.MockTransport`` so the
suite never makes a real network call.
"""

from __future__ import annotations

import httpx
import pytest
import structlog

from app.auth import otp
from app.auth.email import (
    ConsoleEmailSender,
    EmailSender,
    EmailSendError,
    ResendEmailSender,
)


# ---------------------------------------------------------------------------
# ConsoleEmailSender
# ---------------------------------------------------------------------------


async def test_console_sender_emits_structured_log() -> None:
    sender = ConsoleEmailSender()

    with structlog.testing.capture_logs() as records:
        await sender.send_otp(to="Alice@X.com", code="012345")

    matching = [
        r for r in records if r.get("event") == "auth.email.console_otp_sent"
    ]
    assert len(matching) == 1, records
    event = matching[0]
    assert event["email_hash"] == otp.email_hash("Alice@X.com")
    assert event["code"] == "012345"
    assert "to" not in event  # raw email must not leak


async def test_console_sender_never_prints(capsys) -> None:
    sender = ConsoleEmailSender()
    await sender.send_otp(to="alice@x.com", code="123456")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "email",
    ["ALICE@X.COM", "Alice@x.com", "  alice@x.com  "],
)
async def test_console_email_hash_matches_otp_module(email: str) -> None:
    sender = ConsoleEmailSender()
    with structlog.testing.capture_logs() as records:
        await sender.send_otp(to=email, code="111111")
    evt = next(r for r in records if r.get("event") == "auth.email.console_otp_sent")
    assert evt["email_hash"] == otp.email_hash(email)


# ---------------------------------------------------------------------------
# Protocol conformance (runtime_checkable)
# ---------------------------------------------------------------------------


def test_isinstance_protocol_conformance() -> None:
    assert isinstance(ConsoleEmailSender(), EmailSender)
    assert isinstance(
        ResendEmailSender(api_key="k", from_="f", timeout=1.0),
        EmailSender,
    )


# ---------------------------------------------------------------------------
# ResendEmailSender
# ---------------------------------------------------------------------------


def _mock_transport(responder):
    """Build an ``httpx.MockTransport`` wrapping ``responder``."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return responder(request)

    return httpx.MockTransport(_handler)


async def test_resend_happy_path() -> None:
    captured: dict = {}

    def _ok(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("authorization")
        captured["json"] = request.read()
        return httpx.Response(200, json={"id": "em_abc"})

    client = httpx.AsyncClient(transport=_mock_transport(_ok))
    sender = ResendEmailSender(
        api_key="k_test",
        from_="minimalist <no-reply@example.com>",
        timeout=5.0,
        http_client=client,
    )
    try:
        await sender.send_otp(to="bob@x.com", code="123456")
    finally:
        await client.aclose()

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer k_test"

    import json as _json
    body = _json.loads(captured["json"])
    assert body["from"] == "minimalist <no-reply@example.com>"
    assert body["to"] == "bob@x.com"
    assert isinstance(body["subject"], str) and body["subject"]
    assert "123456" in body["text"]


async def test_resend_non_2xx_raises_email_send_error() -> None:
    def _err(_request):
        return httpx.Response(500, json={"message": "oops"})

    client = httpx.AsyncClient(transport=_mock_transport(_err))
    sender = ResendEmailSender(
        api_key="k", from_="f", timeout=5.0, http_client=client
    )
    try:
        with pytest.raises(EmailSendError) as excinfo:
            await sender.send_otp(to="alice@x.com", code="123456")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "oops"


async def test_resend_non_json_5xx_has_no_detail() -> None:
    def _err(_request):
        return httpx.Response(502, text="bad gateway")

    client = httpx.AsyncClient(transport=_mock_transport(_err))
    sender = ResendEmailSender(
        api_key="k", from_="f", timeout=5.0, http_client=client
    )
    try:
        with pytest.raises(EmailSendError) as excinfo:
            await sender.send_otp(to="alice@x.com", code="123456")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail is None


async def test_resend_timeout_surfaces_as_email_send_error() -> None:
    def _timeout(_request):
        raise httpx.ReadTimeout("slow")

    client = httpx.AsyncClient(transport=_mock_transport(_timeout))
    sender = ResendEmailSender(
        api_key="k", from_="f", timeout=0.1, http_client=client
    )
    try:
        with pytest.raises(EmailSendError) as excinfo:
            await sender.send_otp(to="alice@x.com", code="123456")
    finally:
        await client.aclose()

    assert excinfo.value.status_code is None
    assert excinfo.value.detail == "timeout"


async def test_resend_never_logs_api_key_or_code() -> None:
    """Across all four paths, no log line contains the API key or OTP code."""

    api_key = "k_super_secret_123"

    cases = [
        lambda r: httpx.Response(200, json={"id": "ok"}),
        lambda r: httpx.Response(500, json={"message": "oops"}),
        lambda r: httpx.Response(502, text="bad"),
    ]

    for i, responder in enumerate(cases):
        client = httpx.AsyncClient(transport=_mock_transport(responder))
        sender = ResendEmailSender(
            api_key=api_key,
            from_="f@x.com",
            timeout=1.0,
            http_client=client,
        )
        with structlog.testing.capture_logs() as records:
            try:
                await sender.send_otp(to="alice@x.com", code="919293")
            except EmailSendError:
                pass
        await client.aclose()

        for record in records:
            serialized = str(record)
            assert api_key not in serialized, (i, record)
            assert "919293" not in serialized, (i, record)

    # Timeout path separately (raises directly).
    def _timeout(_request):
        raise httpx.ReadTimeout("slow")

    client = httpx.AsyncClient(transport=_mock_transport(_timeout))
    sender = ResendEmailSender(
        api_key=api_key, from_="f", timeout=0.1, http_client=client
    )
    with structlog.testing.capture_logs() as records:
        try:
            await sender.send_otp(to="alice@x.com", code="919293")
        except EmailSendError:
            pass
    await client.aclose()

    for record in records:
        serialized = str(record)
        assert api_key not in serialized
        assert "919293" not in serialized
