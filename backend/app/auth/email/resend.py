"""Resend email provider -- thin HTTP wrapper, no SDK.

Uses the one-endpoint, one-JSON-body surface of the Resend API
(``POST https://api.resend.com/emails``). Deliberately does **not**
pull in the ``resend`` PyPI SDK; we already ship ``httpx`` and the
upstream surface is small enough that a wrapper is cheaper than a
dependency.

Design references:

- ``docs/specs/feat_auth_002/feat_auth_002.md`` requirement 3.
- ``docs/design/auth-login-and-roles.md`` §8 security row
  "API key never logged".

Logging discipline:

- Emits **nothing** on success (the router emits ``auth.otp.requested``
  once per request, which is the observability anchor).
- On failure, raises :class:`EmailSendError`. The router catches it
  and emits ``auth.otp.send_failed``. This module never logs the API
  key, the recipient email, or the OTP code.
"""

from __future__ import annotations

import httpx

from app.auth.email.base import EmailSender, EmailSendError


_RESEND_ENDPOINT = "https://api.resend.com/emails"
_OTP_SUBJECT = "Your sign-in code"


def _otp_body_text(code: str) -> str:
    """Return the plain-text email body for an OTP delivery.

    Kept as a string literal -- no HTML template engine, no
    personalization beyond the code. The body is intentionally boring
    so the OTP itself is the first thing the recipient sees.
    """

    return (
        "Your sign-in code is:\n\n"
        f"    {code}\n\n"
        "This code expires in 10 minutes. If you did not request it,\n"
        "you can safely ignore this email."
    )


class ResendEmailSender:
    """Send OTP codes through Resend's HTTP API.

    Conforms to :class:`EmailSender`.

    The ``http_client`` constructor parameter lets tests inject a
    pre-built :class:`httpx.AsyncClient` with a ``MockTransport`` so
    the suite never makes a real network call. Production callers
    (the factory) omit it, and the sender builds one on first send
    and reuses it for the lifetime of the app.
    """

    def __init__(
        self,
        *,
        api_key: str,
        from_: str,
        timeout: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._from = from_
        self._timeout = timeout
        self._http_client = http_client
        self._owns_client = http_client is None

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout)

    async def send_otp(self, *, to: str, code: str) -> None:
        payload = {
            "from": self._from,
            "to": to,
            "subject": _OTP_SUBJECT,
            "text": _otp_body_text(code),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        client = self._http_client or self._build_client()
        try:
            try:
                response = await client.post(
                    _RESEND_ENDPOINT,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                raise EmailSendError(
                    status_code=None, detail="timeout"
                ) from exc
            except httpx.HTTPError as exc:
                raise EmailSendError(
                    status_code=None, detail="transport_error"
                ) from exc
        finally:
            if self._http_client is None and self._owns_client:
                # Only close a client we built lazily for this call.
                # A caller-provided client is the caller's concern.
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001 -- defensive
                    pass

        if response.status_code >= 300:
            detail: str | None = None
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = body.get("message")
                    if isinstance(message, str):
                        detail = message
            except ValueError:
                # Body was not JSON; leave detail unset.
                detail = None
            raise EmailSendError(
                status_code=response.status_code,
                detail=detail,
            )

    async def aclose(self) -> None:
        """Close the owned :class:`httpx.AsyncClient`, if any.

        Safe to call more than once. Callers that passed in their own
        client via ``http_client=`` retain ownership of it -- this
        method does not touch a caller-supplied client.
        """

        if self._http_client is not None and self._owns_client:
            try:
                await self._http_client.aclose()
            except Exception:  # noqa: BLE001 -- defensive
                pass


# Runtime-checkable Protocol conformance is verified by
# ``test_auth_email_senders.py`` case 10.
_: EmailSender = ResendEmailSender(  # noqa: F841 -- type-assert
    api_key="_",
    from_="_",
    timeout=1.0,
)


__all__ = ["ResendEmailSender"]
