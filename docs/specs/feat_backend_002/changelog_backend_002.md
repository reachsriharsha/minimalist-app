# Changelog: feat_backend_002

## Added

- `backend/RULES.md` — 21-rule backend rule sheet across six sections (Layout, API, Data layer, Settings and secrets, Logging, Testing). Read by humans during review and by the AutoDev agents at session start.
- `backend/app/items/` — new domain folder containing `__init__.py`, `router.py`, `schemas.py`, `models.py`, and `service.py`. Model of the per-domain layout that RULES.md §1 mandates for every future resource.
- `backend/app/logging.py` — `structlog.processors.CallsiteParameterAdder` on every record so `filename`, `func_name`, and `lineno` appear without caller intervention.
- `backend/app/logging.py` — `redact_sensitive` structlog processor that replaces the value of any key in a fixed denylist (`password`, `authorization`, `token`, `cookie`, `secret`, `api_key`, `set-cookie`, `refresh_token`) with `"***"`, case-insensitively, at every dict depth.
- `backend/tests/test_logging_callsite.py` — verifies the callsite adder on info and exception paths with dynamically computed expected line numbers.
- `backend/tests/test_logging_redaction.py` — unit tests for the redactor covering the seven cases in the test spec table, including the documented list-non-traversal limitation.

## Changed

- `backend/app/db.py` — now declares `Base(DeclarativeBase)` and sets `Base.metadata.naming_convention` to `{pk, fk, ix, uq, ck}` templates. Alembic autogenerate picks this up transparently.
- `backend/app/schemas.py` — retained `HealthResponse`, `DependencyCheck`, `ReadinessResponse`, `ErrorBody`, `ErrorEnvelope`; moved `HelloResponse` to `app/items/schemas.py`.
- `backend/app/api/v1/__init__.py` — includes the router re-exported from `app.items` (previously `app.api.v1.hello`).
- `backend/alembic.ini` — `file_template = %%(rev)s_%%(slug)s` so migration filenames become `<rev>_<slug>.py`.
- `backend/alembic/env.py` — imports `Base` from `app.db` and explicitly imports `app.items.models` so every ORM class registers on `Base.metadata` before `target_metadata` is read.
- `docs/specs/README.md` — `feat_backend_002` roster row advanced from `In Spec` to `In Build`.

## Removed

- `backend/app/models.py` — `Base` moved to `app/db.py`; `Item` moved to `app/items/models.py`.
- `backend/app/api/v1/hello.py` — replaced by `backend/app/items/router.py`.

## External behavior

No user-visible change. `GET /api/v1/hello` returns a body of the same shape and content as before (`{message, item_name, hello_count}`), with the same `200`/`503` status-code contract. The full external test suite (7 cases in `tests/`) passes against the refactored stack.

## Migration notes

- The alembic naming convention applies to migrations generated after this PR; existing migration `0001_create_items.py` retains its default constraint names. Dropping constraints on the existing table uses the database-side name, so the mismatch is invisible at runtime.
- No `.env`, compose, or deployment changes. No new dependencies.
