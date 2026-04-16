"""Structured JSON logging configuration.

Routes both :mod:`logging` and :mod:`structlog` through a shared
:class:`structlog.stdlib.ProcessorFormatter` so every log record produced by
application code, FastAPI, or uvicorn is rendered as a single JSON object per
line on stdout.

Two guarantees are baked in at the logger level so call sites cannot forget
them:

1. Every record carries ``filename``, ``func_name``, and ``lineno``, added by
   :class:`structlog.processors.CallsiteParameterAdder`.
2. Keys matching a fixed case-insensitive denylist of sensitive names are
   replaced with ``"***"`` at every dict depth by :func:`redact_sensitive`.

See ``backend/RULES.md`` §5 for the ruleset these processors enforce.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False

# Keys whose values are replaced with ``"***"`` before rendering. Matching is
# case-insensitive (via ``.lower()``) and applies at every dict depth.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "authorization",
        "token",
        "cookie",
        "secret",
        "api_key",
        "set-cookie",
        "refresh_token",
    }
)


def _redact(value: Any) -> Any:
    """Recursively scrub denylisted keys inside a nested dict value.

    Lists, tuples, and sets are intentionally not traversed: logging a
    collection of user-shaped dicts is a smell ``RULES.md`` §5 calls out. Any
    other value type is returned as-is.
    """

    if isinstance(value, dict):
        return {
            k: (
                "***"
                if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS
                else _redact(v)
            )
            for k, v in value.items()
        }
    return value


def redact_sensitive(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: scrub sensitive keys at every dict depth.

    Contract:

    - Top-level keys in ``event_dict`` whose lowercase form is in
      :data:`_SENSITIVE_KEYS` have their value replaced with ``"***"``.
    - Nested dict values are walked recursively with the same rules.
    - Lists, tuples, and sets are not traversed.
    - Non-string keys are left as-is (``k.lower()`` would fail on them, and
      they should not appear in structlog event dicts).

    The denylist is a module-level :class:`frozenset`; extending it is a
    one-line change.
    """

    return {
        k: (
            "***"
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS
            else _redact(v)
        )
        for k, v in event_dict.items()
    }


def configure_logging(level: str = "INFO") -> None:
    """Configure stdlib logging and structlog to emit JSON.

    Safe to call multiple times; only the first call performs the wiring.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    callsite = structlog.processors.CallsiteParameterAdder(
        parameters=(
            structlog.processors.CallsiteParameter.FILENAME,
            structlog.processors.CallsiteParameter.FUNC_NAME,
            structlog.processors.CallsiteParameter.LINENO,
        ),
    )

    # Processor chain (order matters):
    #   merge_contextvars -> add_log_level -> TimeStamper
    #     -> CallsiteParameterAdder (filename/func_name/lineno)
    #     -> StackInfoRenderer
    #     -> redact_sensitive
    #     -> format_exc_info (tail, added below)
    #     -> JSONRenderer (final, added below)
    #
    # ``redact_sensitive`` runs after ``StackInfoRenderer`` but before
    # ``format_exc_info``: stack info and formatted exc_info are rendered
    # strings, not keyed user data, so we scrub keys first and let the
    # traceback pass through untouched.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        callsite,
        structlog.processors.StackInfoRenderer(),
        redact_sensitive,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Remove any handlers a previous test or library attached so we don't
    # double-emit log lines.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Make uvicorn's noisy access/error loggers flow through the same handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(numeric_level)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name``."""

    return structlog.get_logger(name)


__all__ = [
    "configure_logging",
    "get_logger",
    "redact_sensitive",
]
