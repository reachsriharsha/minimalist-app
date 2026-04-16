"""Pydantic response schemas for the ``items`` domain."""

from __future__ import annotations

from pydantic import BaseModel


class HelloResponse(BaseModel):
    message: str
    item_name: str
    hello_count: int


__all__ = ["HelloResponse"]
