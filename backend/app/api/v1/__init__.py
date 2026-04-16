"""Version 1 API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.auth import router as auth_router
from app.items import router as items_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(items_router)
api_v1_router.include_router(auth_router, prefix="/auth")

__all__ = ["api_v1_router"]
