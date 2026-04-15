"""Pydantic response models for the scaffold's public endpoints."""

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


class HelloResponse(BaseModel):
    message: str
    item_name: str
    hello_count: int


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
    "HelloResponse",
    "ErrorBody",
    "ErrorEnvelope",
]
