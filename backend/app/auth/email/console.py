"""Console email sender -- logs the OTP code, never emails it.

Use in dev and test. The operator flow is documented in
``docs/deployment/email-otp-setup.md``:

.. code-block:: bash

    docker compose logs backend | grep auth.email.console_otp_sent | tail -n 1

The log event name includes ``console`` so an accidental production
use of this sender surfaces loudly in any log-search tool.
"""

from __future__ import annotations

from app.auth import otp
from app.auth.email.base import EmailSender
from app.logging import get_logger


class ConsoleEmailSender:
    """Log the OTP code through the standard ``app.logging`` chain.

    Conforms to :class:`EmailSender`. Emits exactly one event per send:
    ``auth.email.console_otp_sent`` with ``email_hash`` and ``code``
    fields. This is the documented dev-only exception to the
    "never log OTP codes" rule -- the raw email address is deliberately
    **not** logged.
    """

    async def send_otp(self, *, to: str, code: str) -> None:
        log = get_logger(__name__)
        log.info(
            "auth.email.console_otp_sent",
            email_hash=otp.email_hash(to),
            code=code,
        )


# Runtime-checkable Protocol conformance is verified by
# ``test_auth_email_senders.py`` case 10.
_: EmailSender = ConsoleEmailSender()  # noqa: F841 -- type-assert


__all__ = ["ConsoleEmailSender"]
