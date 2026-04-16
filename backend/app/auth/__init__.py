"""``auth`` domain: users, roles, identities, sessions, authorization primitives.

Re-exports :data:`router` so the versioned API aggregator can include it
with a single import, mirroring the layout established by
:mod:`app.items`. See ``docs/design/auth-login-and-roles.md`` and
``docs/specs/feat_auth_001/`` for the full design.
"""

from app.auth.router import router

__all__ = ["router"]
