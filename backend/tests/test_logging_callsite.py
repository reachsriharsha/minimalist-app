"""Tests for the ``CallsiteParameterAdder`` addition to ``app.logging``.

These tests exercise the fully wired logging chain: they call
:func:`configure_logging` and capture the JSON that the root handler's
formatter emits, so a regression in processor ordering or configuration
(not just the processor function in isolation) is caught.
"""

from __future__ import annotations

import json
import logging
from inspect import currentframe

import pytest
import structlog

from app.logging import configure_logging, get_logger


class _JsonCapture(logging.Handler):
    """Collect rendered JSON records emitted by the root handler.

    ``configure_logging`` installs a single stdout handler with a
    ``ProcessorFormatter``; we attach a second handler with the same
    formatter so tests can read the exact bytes the production handler
    would produce without intercepting stdout.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(self.format(record))
        except Exception:  # noqa: BLE001 — do not mask formatter bugs
            self.handleError(record)


@pytest.fixture
def json_capture(monkeypatch):
    """Configure logging (once) and attach a JSON-capturing handler.

    ``configure_logging`` short-circuits after the first call thanks to the
    module-level ``_CONFIGURED`` flag; we reset it via ``monkeypatch`` so
    every test gets a fresh wiring and a fresh capture handler.
    """

    monkeypatch.setattr("app.logging._CONFIGURED", False)
    # Also clear structlog's cached logger instances so the new processor
    # chain takes effect for ``structlog.get_logger`` calls made below.
    structlog.reset_defaults()

    configure_logging("DEBUG")

    root = logging.getLogger()
    # ``configure_logging`` has already installed the formatter on the
    # stdout handler; reuse it so the capture handler renders identical JSON.
    formatter = root.handlers[0].formatter
    capture = _JsonCapture()
    capture.setFormatter(formatter)
    capture.setLevel(logging.DEBUG)
    root.addHandler(capture)
    try:
        yield capture
    finally:
        root.removeHandler(capture)


def test_info_log_carries_callsite(json_capture):
    """An ``info`` log carries ``filename``, ``func_name``, and ``lineno``."""

    log = get_logger("test_callsite")
    expected_lineno = currentframe().f_lineno + 1
    log.info("probe", detail="x")

    assert json_capture.records, "no log records captured"
    payload = json.loads(json_capture.records[-1])

    assert payload["event"] == "probe"
    assert payload["detail"] == "x"
    assert payload["filename"] == "test_logging_callsite.py"
    assert payload["func_name"] == "test_info_log_carries_callsite"
    assert payload["lineno"] == expected_lineno


def test_exception_log_carries_trace(json_capture):
    """An ``exception`` log preserves the traceback and callsite metadata."""

    log = get_logger("test_callsite")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        expected_lineno = currentframe().f_lineno + 1
        log.exception("failed", op="probe")

    assert json_capture.records, "no log records captured"
    payload = json.loads(json_capture.records[-1])

    assert payload["event"] == "failed"
    assert payload["op"] == "probe"
    assert payload["filename"] == "test_logging_callsite.py"
    assert payload["func_name"] == "test_exception_log_carries_trace"
    assert payload["lineno"] == expected_lineno

    # ``format_exc_info`` renders the traceback into the ``exception`` key.
    # Accept either ``exception`` or ``stack_info`` to stay robust across
    # minor structlog version differences.
    trace = payload.get("exception") or payload.get("stack_info") or ""
    assert "RuntimeError" in trace
    assert "boom" in trace
