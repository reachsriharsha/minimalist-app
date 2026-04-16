"""Unit tests for the ``redact_sensitive`` structlog processor.

The processor is a pure function over an event dict; no logger instance is
needed. Each case is a table row from ``docs/specs/feat_backend_002/
test_backend_002.md``.
"""

from __future__ import annotations

from app.logging import redact_sensitive


def _redact(event_dict):
    """Call the processor with placeholder ``logger`` / ``method_name``."""

    return redact_sensitive(None, "info", event_dict)


def test_denylisted_top_level_key_is_scrubbed():
    out = _redact({"password": "hunter2", "user_id": 7})
    assert out == {"password": "***", "user_id": 7}


def test_non_denylisted_top_level_keys_pass_through():
    payload = {"item_id": 42, "item_name": "widget"}
    out = _redact(payload)
    assert out == payload


def test_denylisted_key_in_nested_dict_is_scrubbed():
    out = _redact(
        {"request": {"authorization": "Bearer x", "path": "/"}}
    )
    assert out == {"request": {"authorization": "***", "path": "/"}}


def test_denylisted_key_in_deeply_nested_dict_is_scrubbed():
    out = _redact({"a": {"b": {"password": "p"}}})
    assert out == {"a": {"b": {"password": "***"}}}


def test_mixed_case_denylisted_key_is_scrubbed():
    # Case-insensitive match; the original key casing is preserved.
    out = _redact({"Authorization": "Bearer x"})
    assert out == {"Authorization": "***"}


def test_non_string_key_is_passed_through():
    # ``k.lower()`` would blow up on a non-string; the processor guards it.
    out = _redact({1: "ok", "token": "t"})
    assert out == {1: "ok", "token": "***"}


def test_list_containing_dict_is_not_traversed():
    # Documented limitation in RULES.md §5 and test spec:
    # lists/tuples/sets are not walked, so nested secrets inside a list
    # of dicts will leak unless the caller flattens them first.
    payload = {"users": [{"password": "p"}]}
    out = _redact(payload)
    assert out == payload
