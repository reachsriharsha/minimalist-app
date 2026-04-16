"""``items`` domain: the demo resource backing ``GET /api/v1/hello``.

Re-exports :data:`router` so the versioned API aggregator can include it with
a single import.
"""

from app.items.router import router

__all__ = ["router"]
