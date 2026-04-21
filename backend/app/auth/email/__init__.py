"""Email-sender package for the ``auth`` domain.

Public surface:

- :class:`EmailSender` -- the one-method protocol.
- :class:`ConsoleEmailSender`, :class:`ResendEmailSender` --
  implementations.
- :func:`build_email_sender` -- factory + startup validation.
- :func:`get_email_sender` -- FastAPI dependency that reads
  ``app.state.email_sender``.
- :class:`EmailSendError`, :class:`EmailProviderConfigError` --
  typed error classes.

The package is deliberately small. If/when a future feature needs
arbitrary transactional email, the package hoists to ``app/email/``
(per §5.1 of the design doc) -- this ``app.auth.email`` namespace is
scoped to OTP delivery.
"""

from __future__ import annotations

from fastapi import Request

from app.auth.email.base import (
    EmailProviderConfigError,
    EmailSender,
    EmailSendError,
)
from app.auth.email.console import ConsoleEmailSender
from app.auth.email.factory import build_email_sender
from app.auth.email.resend import ResendEmailSender


async def get_email_sender(request: Request) -> EmailSender:
    """FastAPI dependency returning the app-scoped email sender.

    Mirrors :func:`app.redis_client.get_redis` -- the sender is built
    once at lifespan startup and lives on ``app.state.email_sender``.
    """

    return request.app.state.email_sender


__all__ = [
    "EmailSender",
    "EmailSendError",
    "EmailProviderConfigError",
    "ConsoleEmailSender",
    "ResendEmailSender",
    "build_email_sender",
    "get_email_sender",
]
