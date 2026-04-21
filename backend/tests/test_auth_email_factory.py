"""Unit tests for :func:`app.auth.email.factory.build_email_sender`."""

from __future__ import annotations

import pytest

from app.auth.email import (
    ConsoleEmailSender,
    EmailProviderConfigError,
    ResendEmailSender,
    build_email_sender,
)
from app.settings import Settings


def test_console_path_returns_console_sender() -> None:
    sender = build_email_sender(Settings(email_provider="console"))
    assert isinstance(sender, ConsoleEmailSender)


def test_resend_happy_path_returns_resend_sender() -> None:
    sender = build_email_sender(
        Settings(
            email_provider="resend",
            resend_api_key="k_abc",
            email_from="f@example.com",
        )
    )
    assert isinstance(sender, ResendEmailSender)


def test_resend_missing_api_key_raises() -> None:
    with pytest.raises(EmailProviderConfigError) as excinfo:
        build_email_sender(
            Settings(
                email_provider="resend",
                resend_api_key="",
                email_from="f@example.com",
            )
        )
    assert "RESEND_API_KEY" in str(excinfo.value)


def test_resend_missing_from_raises() -> None:
    with pytest.raises(EmailProviderConfigError) as excinfo:
        build_email_sender(
            Settings(
                email_provider="resend",
                resend_api_key="k",
                email_from="",
            )
        )
    assert "EMAIL_FROM" in str(excinfo.value)


def test_unknown_provider_rejected_at_settings_level() -> None:
    # ``email_provider`` is a ``Literal[...]`` so pydantic rejects
    # unknown values at instantiation. The factory does not run.
    with pytest.raises(Exception):
        Settings(email_provider="sendgrid")


def test_test_otp_set_in_dev_raises() -> None:
    with pytest.raises(EmailProviderConfigError) as excinfo:
        build_email_sender(
            Settings(
                env="dev",
                test_otp_email="alice@x.com",
                test_otp_code="123456",
            )
        )
    assert "TEST_OTP_EMAIL" in str(excinfo.value)


def test_test_otp_set_in_prod_raises() -> None:
    with pytest.raises(EmailProviderConfigError):
        build_email_sender(
            Settings(
                env="prod",
                test_otp_email="alice@x.com",
                test_otp_code="123456",
            )
        )


def test_test_otp_partial_in_dev_still_refuses() -> None:
    """Any single field being non-empty in non-test is still a startup error.

    Mirrors the factory implementation: the guard fires on ``email
    OR code`` being truthy, not on ``email AND code``. The
    fixture's runtime gating elsewhere (in the router) requires both,
    but the defense-in-depth startup check is stricter.
    """

    with pytest.raises(EmailProviderConfigError):
        build_email_sender(
            Settings(
                env="dev",
                test_otp_email="alice@x.com",
                test_otp_code="",
            )
        )


def test_test_otp_partial_in_test_does_not_raise() -> None:
    """Partial (either field empty) in test is a no-op, not an error."""

    sender = build_email_sender(
        Settings(
            env="test",
            test_otp_email="alice@x.com",
            test_otp_code="",
        )
    )
    assert isinstance(sender, ConsoleEmailSender)


def test_test_otp_empty_empty_in_dev_does_not_raise() -> None:
    sender = build_email_sender(
        Settings(env="dev", test_otp_email="", test_otp_code="")
    )
    assert isinstance(sender, ConsoleEmailSender)


def test_test_otp_both_set_in_test_does_not_raise() -> None:
    sender = build_email_sender(
        Settings(
            env="test",
            test_otp_email="alice@x.com",
            test_otp_code="123456",
        )
    )
    assert isinstance(sender, ConsoleEmailSender)
