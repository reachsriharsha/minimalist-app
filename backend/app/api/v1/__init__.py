"""Version 1 API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import hello

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(hello.router)

__all__ = ["api_v1_router"]
