"""The minimalist-app backend package.

Exposes the :func:`create_app` factory used by ASGI servers and tests.
"""

from app.main import create_app

__all__ = ["create_app", "__version__"]

__version__ = "0.1.0"
