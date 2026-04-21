"""Protocol + error classes for the email-sender abstraction.

Kept minimal on purpose: OTP delivery is the only consumer in
``feat_auth_002``. If a future feature needs arbitrary transactional
email the package will hoist to ``app/email/`` and ``send_otp`` either
stays as a convenience wrapper or is replaced with a general
``send(...)`` method at that time.

The :class:`EmailSender` protocol is marked ``runtime_checkable`` so
tests can assert ``isinstance(sender, EmailSender)`` on both concrete
implementations (see ``test_auth_email_senders.py`` case 10).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    """Minimal protocol: deliver one OTP code to one address.

    Both concrete implementations (:class:`app.auth.email.console.ConsoleEmailSender`
    and :class:`app.auth.email.resend.ResendEmailSender`) conform to this
    shape. The router calls ``await sender.send_otp(to=..., code=...)``
    and catches :class:`EmailSendError` so a provider outage does not
    poison the ``/otp/request`` response.
    """

    async def send_otp(self, *, to: str, code: str) -> None:
        """Deliver ``code`` to ``to`` through the provider.

        Contract:

        - Raise :class:`EmailSendError` on any provider-reported
          failure (non-2xx HTTP, timeout, auth error). The router
          logs the failure and still returns 204.
        - Never log the raw ``to`` value or the ``code`` **except**
          inside :class:`ConsoleEmailSender`, whose entire purpose is
          the dev-mode "grep the log for the code" flow.
        """
        ...  # pragma: no cover -- protocol method


class EmailSendError(Exception):
    """Raised by a sender when the provider rejects the request.

    Carries the HTTP status (``None`` for timeouts/transport errors)
    and an optional ``detail`` string lifted from the provider's JSON
    error envelope. Never carries the API key or the code.
    """

    def __init__(
        self,
        *,
        status_code: int | None,
        detail: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        parts = []
        if status_code is not None:
            parts.append(f"status={status_code}")
        if detail:
            parts.append(f"detail={detail}")
        super().__init__("email send failed" + (" " + " ".join(parts) if parts else ""))


class EmailProviderConfigError(Exception):
    """Raised at startup when the email provider is misconfigured.

    Examples: ``EMAIL_PROVIDER=resend`` with an empty ``RESEND_API_KEY``;
    an unknown provider string; ``TEST_OTP_EMAIL`` / ``TEST_OTP_CODE``
    set outside ``ENV=test``.

    Surfacing this at lifespan startup (via :func:`build_email_sender`)
    means ``make up`` fails loudly rather than a user discovering the
    problem mid-login.
    """


__all__ = [
    "EmailSender",
    "EmailSendError",
    "EmailProviderConfigError",
]
