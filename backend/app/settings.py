"""Application settings loaded from environment variables and ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view over the environment.

    Values are sourced from (in priority order): process environment variables,
    then ``backend/.env``. All fields have safe development defaults so the app
    can be imported and ``/healthz`` can serve traffic without any external
    services running.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "minimalist-app-backend"
    env: Literal["dev", "test", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    )
    redis_url: str = "redis://localhost:6379/0"

    request_id_header: str = "X-Request-ID"

    # ---- Auth (feat_auth_001) -------------------------------------------
    # Session cookie and role-bootstrap controls for the auth foundation.
    # See ``docs/design/auth-login-and-roles.md`` §§2, 8, 11 for rationale.
    session_cookie_name: str = "session"
    session_ttl_seconds: int = 86400
    session_cookie_secure: bool = False
    # Raw comma-separated list; parse via :attr:`admin_emails_set`. Empty
    # string (the default) yields an empty set, so a fresh clone grants
    # admin to nobody.
    admin_emails: str = ""

    @property
    def admin_emails_set(self) -> frozenset[str]:
        """Parsed, lower-cased set of bootstrap-admin email addresses.

        Empty fragments (from trailing or duplicate commas) are skipped.
        Whitespace around each entry is stripped. Matching against a user
        email is case-insensitive because the stored form is lower-cased
        and callers lower-case the probe value.
        """

        return frozenset(
            e.strip().lower()
            for e in self.admin_emails.split(",")
            if e.strip()
        )

    # ---- Email / OTP (feat_auth_002) ------------------------------------
    # Controls how OTP codes are delivered, how long they live, and how
    # aggressively the rate-limiter throttles ``/auth/otp/request``. See
    # ``docs/specs/feat_auth_002/feat_auth_002.md`` §11 for the authoritative
    # list and defaults.
    email_provider: Literal["console", "resend"] = "console"
    email_from: str = "minimalist-app <noreply@example.com>"
    email_provider_timeout_seconds: float = 5.0
    resend_api_key: str = ""

    otp_code_ttl_seconds: int = 600
    otp_max_attempts: int = 5
    otp_rate_per_minute: int = 1
    otp_rate_per_hour: int = 10

    # Test-only OTP fixture (see feat_auth_002 spec requirement 9).
    # Intentionally has NO compiled-in default beyond empty string;
    # populated from env ONLY in the test environment. Must stay empty
    # in dev/prod. ``app.auth.email.factory.build_email_sender`` refuses
    # to start when either is set with ``env != "test"``.
    test_otp_email: str = ""
    test_otp_code: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings. Intended for tests that mutate env vars."""

    get_settings.cache_clear()
