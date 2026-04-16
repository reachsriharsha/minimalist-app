# Implementation Notes: feat_backend_002

Built on branch `build/feat_backend_002` from `main` at commit `1eef91b` (spec PR #17 merge). Implements the design spec verbatim with one small notation fix (see below).

## What shipped

Three disjoint pieces, one build:

1. **`backend/RULES.md`** — a 21-rule, 6-section rule sheet covering Layout, API, Data layer, Settings and secrets, Logging, and Testing. Each rule is one declarative sentence plus a one-line *why*. A short "Known redactor limitations" subsection under §5 calls out the three escapes the redactor does not cover (lists, pre-rendered strings, honest key naming).
2. **`backend/app/logging.py`** — two processor additions wired into the shared chain:
   - `structlog.processors.CallsiteParameterAdder(FILENAME, FUNC_NAME, LINENO)` placed between `TimeStamper` and `StackInfoRenderer`, so every line (app code, FastAPI, uvicorn) carries source location.
   - A new module-level `redact_sensitive(logger, method, event_dict)` processor backed by a `frozenset` denylist (`password`, `authorization`, `token`, `cookie`, `secret`, `api_key`, `set-cookie`, `refresh_token`). Case-insensitive key match, recursive into nested dicts, leaves lists/tuples/sets alone, guards non-string keys with `isinstance(k, str)` before calling `.lower()`.
   The processor order is pinned in the module docstring and a comment block inside `configure_logging`. `redact_sensitive` sits after `StackInfoRenderer` and before `format_exc_info` so keyed user data is scrubbed but the rendered traceback passes through untouched.
3. **`app/items/` domain move + `Base` relocation** — mechanical refactor:
   - Created `backend/app/items/{__init__.py, router.py, schemas.py, models.py, service.py}`.
   - `Base(DeclarativeBase)` moved from `app/models.py` (deleted) into `app/db.py`, with `Base.metadata.naming_convention = NAMING_CONVENTION` applied at class-creation time.
   - `app/schemas.py` kept only the cross-cutting schemas (`HealthResponse`, `DependencyCheck`, `ReadinessResponse`, `ErrorBody`, `ErrorEnvelope`); `HelloResponse` moved to `app/items/schemas.py`.
   - `app/api/v1/__init__.py` imports `router` from `app.items` instead of `app.api.v1.hello`. The old `app/api/v1/hello.py` is deleted.
   - `backend/alembic/env.py` imports `Base` from `app.db` and explicitly imports `app.items.models` (noqa F401) so every ORM class is registered on `Base.metadata` before alembic reads `target_metadata`.
   - `backend/alembic.ini` gained `file_template = %%(rev)s_%%(slug)s` in the `[alembic]` section.

## Deviations from the design spec

- **Rule count.** The feature spec requires 21 rules; the design spec prose says "19" while its section lists total 21. Implemented 21, matching the feature spec.
- **`app/items/__init__.py`.** The design spec shows `from app.items.router import router`. Implemented verbatim (no star imports, no side-effect modules).
- **Alembic `env.py`.** The spec says the change is "path only." Added one additional line — a side-effect import of `app.items.models` — because `Base` relocating out of the same module that declared `Item` would otherwise leave `target_metadata` empty at alembic autogenerate time. Documented inline with a one-line comment.

## Test coverage added

- `backend/tests/test_logging_callsite.py` — 2 cases (info log, exception log), both assert `filename`, `func_name`, `lineno`, and (for the exception case) the rendered traceback containing the raised exception class and message. Line numbers are computed dynamically via `inspect.currentframe().f_lineno + 1` so edits to surrounding lines do not cascade into fragile test failures.
- `backend/tests/test_logging_redaction.py` — 7 cases from the test spec table: top-level denylisted key, non-denylisted passthrough, nested-dict scrub, deeply-nested scrub, mixed-case match, non-string key, list-of-dicts documented limitation.

`backend/tests/test_hello.py` needed no import changes — it is a black-box HTTP test that never imported from the moved modules.

## Self-review

- Diff size: 15 files changed, +452 / -31. Most of the insertion is the new RULES.md (50 lines) and the two test files (173 lines).
- Grep confirmed zero remaining references to `app.models` or `app.api.v1.hello` anywhere under `backend/`.
- `uv run pytest` in `backend/` passes locally: 20 passed, 1 skipped (`test_hello.py` skips on bare checkout because Postgres is not reachable — expected per the existing pattern).
- `./test.sh --down` passes: 7/7 external functional tests green against the docker-compose stack brought up fresh.
- No new dependencies. `structlog.processors.CallsiteParameterAdder` is already available in the installed `structlog>=24.1`.

## Risks and follow-ups

- The alembic naming convention is applied going forward only; the existing `0001_create_items.py` migration keeps its default constraint names. This is the behavior the feature spec asks for.
- No linter catches the "every log line carries a domain kwarg" rule — it remains a human-review item, as decided during spec brainstorming.
- The redactor's list/tuple/set non-traversal is documented in RULES.md §5 and in the test suite. If a future feature needs deep-collection scrubbing, wrap `_redact` to recurse through list items too, but do it explicitly so the cost (log-line size, CPU on hot paths) is visible.
