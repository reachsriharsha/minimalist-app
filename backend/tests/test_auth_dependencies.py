"""Unit tests for :mod:`app.auth.dependencies`.

These do not spin up the FastAPI app. They exercise the three helpers
(``current_user``, ``require_authenticated``, ``require_roles``) directly
against a fabricated ``request.state.auth`` to verify:

- Authentication precedes authorization (401 before 403).
- ``require_roles`` has OR semantics across the names it is given.
- Missing state is treated the same as explicit ``None``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.auth.dependencies import (
    current_user,
    require_authenticated,
    require_roles,
)
from app.auth.schemas import AuthContext


def _fake_request(auth: Any) -> Any:
    """Build a minimal object exposing ``state.auth`` for the dependency."""

    return SimpleNamespace(state=SimpleNamespace(auth=auth))


def _ctx(roles: tuple[str, ...] = ("user",)) -> AuthContext:
    return AuthContext(
        user_id=1,
        email="a@x.com",
        roles=roles,
        session_id="a" * 64,
    )


def test_current_user_returns_context_when_authenticated():
    ctx = _ctx()
    req = _fake_request(ctx)
    assert current_user(req) is ctx


def test_current_user_raises_401_when_none():
    req = _fake_request(None)
    with pytest.raises(HTTPException) as ei:
        current_user(req)
    assert ei.value.status_code == 401
    assert ei.value.detail == "not_authenticated"


def test_require_authenticated_is_an_alias_for_current_user():
    # Same function object; same semantics.
    assert require_authenticated is current_user

    req = _fake_request(None)
    with pytest.raises(HTTPException) as ei:
        require_authenticated(req)
    assert ei.value.status_code == 401
    assert ei.value.detail == "not_authenticated"


def test_require_roles_single_match():
    dep = require_roles("user")
    ctx = _ctx(("user",))
    req = _fake_request(ctx)
    assert dep(req) is ctx


def test_require_roles_single_miss_returns_403():
    dep = require_roles("admin")
    ctx = _ctx(("user",))
    req = _fake_request(ctx)
    with pytest.raises(HTTPException) as ei:
        dep(req)
    assert ei.value.status_code == 403
    assert ei.value.detail == "forbidden"


def test_require_roles_or_semantics_first_matches():
    dep = require_roles("admin", "user")
    ctx = _ctx(("admin",))
    req = _fake_request(ctx)
    assert dep(req) is ctx


def test_require_roles_or_semantics_second_matches():
    dep = require_roles("admin", "user")
    ctx = _ctx(("user",))
    req = _fake_request(ctx)
    assert dep(req) is ctx


def test_require_roles_neither_matches_returns_403():
    dep = require_roles("admin", "user")
    ctx = _ctx(("guest",))
    req = _fake_request(ctx)
    with pytest.raises(HTTPException) as ei:
        dep(req)
    assert ei.value.status_code == 403
    assert ei.value.detail == "forbidden"


def test_require_roles_no_session_returns_401_not_403():
    """Unauthenticated wins over unauthorized."""

    dep = require_roles("admin")
    req = _fake_request(None)
    with pytest.raises(HTTPException) as ei:
        dep(req)
    assert ei.value.status_code == 401
    assert ei.value.detail == "not_authenticated"
