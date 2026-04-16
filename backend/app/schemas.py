"""Pydantic response models shared across the scaffold's infra endpoints.

Per ``backend/RULES.md`` §1, per-domain schemas live under the domain folder
(e.g., :mod:`app.items.schemas`). This module keeps only the cross-cutting
schemas: health/readiness envelopes and the shared error envelope.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DependencyCheck(BaseModel):
    db: str
    redis: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: DependencyCheck


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


__all__ = [
    "HealthResponse",
    "DependencyCheck",
    "ReadinessResponse",
    "ErrorBody",
    "ErrorEnvelope",
]
