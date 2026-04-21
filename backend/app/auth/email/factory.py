"""Provider factory + startup validation for the email sender.

Called once at app-lifespan startup (see :func:`app.main._make_lifespan`)
and stashes the built sender on ``app.state.email_sender``. The
``get_email_sender`` dependency in :mod:`app.auth.email` reads it off
there for request handlers.

Validation responsibilities (all raised as
:class:`EmailProviderConfigError`):

- Unknown provider string.
- ``EMAIL_PROVIDER=resend`` with an empty ``RESEND_API_KEY``.
- ``EMAIL_PROVIDER=resend`` with an empty ``EMAIL_FROM``.
- ``TEST_OTP_EMAIL`` or ``TEST_OTP_CODE`` populated when
  ``ENV != "test"``. This last one is defense-in-depth: the fixture
  is a deliberate test-only injection point; an ops-team accident
  that sets it in production must break the build, not silently
  pre-authorize a canary account.
"""

from __future__ import annotations

from app.auth.email.base import (
    EmailProviderConfigError,
    EmailSender,
)
from app.auth.email.console import ConsoleEmailSender
from app.auth.email.resend import ResendEmailSender
from app.settings import Settings


def build_email_sender(settings: Settings) -> EmailSender:
    """Construct the configured :class:`EmailSender`.

    Raises :class:`EmailProviderConfigError` when the settings are
    inconsistent. Safe to call more than once; it has no side effects
    beyond validation + object construction.
    """

    # ---- Defense-in-depth: refuse to build outside env=test when the
    # test-OTP fixture is populated. This catches a misconfigured
    # production ``.env`` before any request is served.
    if settings.env != "test" and (
        settings.test_otp_email or settings.test_otp_code
    ):
        raise EmailProviderConfigError(
            "TEST_OTP_EMAIL / TEST_OTP_CODE are set but ENV != 'test'. "
            "These variables must be empty outside the test environment. "
            "Clear them in your .env or set ENV=test."
        )

    provider = settings.email_provider
    if provider == "console":
        return ConsoleEmailSender()

    if provider == "resend":
        if not settings.resend_api_key:
            raise EmailProviderConfigError(
                "EMAIL_PROVIDER=resend but RESEND_API_KEY is empty. "
                "Populate RESEND_API_KEY or switch EMAIL_PROVIDER=console "
                "for local development."
            )
        if not settings.email_from:
            raise EmailProviderConfigError(
                "EMAIL_PROVIDER=resend but EMAIL_FROM is empty. "
                "Set EMAIL_FROM to the verified sending address."
            )
        return ResendEmailSender(
            api_key=settings.resend_api_key,
            from_=settings.email_from,
            timeout=settings.email_provider_timeout_seconds,
        )

    # ``Settings.email_provider`` is a ``Literal[...]`` so pydantic
    # normally rejects unknown values at instantiation; guard anyway
    # in case a test bypasses validation via ``model_construct``.
    raise EmailProviderConfigError(
        f"Unknown EMAIL_PROVIDER: {provider!r}. "
        "Expected one of: 'console', 'resend'."
    )


__all__ = ["build_email_sender"]
