# Feature: Backend rules and logging discipline

## Problem Statement

`feat_backend_001` landed a runnable FastAPI scaffold but said nothing about **how** future code should be shaped, what a correct log line looks like, or where a new resource's files belong. Every follow-up feature, every autodev-generated PR, and every human contributor is left to reinvent those decisions.

The fastapi-best-practices repository (zhanymkanov) collects a well-regarded set of conventions for FastAPI projects. Adopting the full set would be over-engineering for a minimalist template, but ignoring it means the scaffold has no teachable shape. This feature codifies a trimmed, template-scaled subset as **`backend/RULES.md`**, updates the running scaffold to match the rules it documents, and adds two small runtime pieces that make the one non-negotiable rule — impeccable logging — structurally guaranteed instead of merely suggested.

The one mandatory requirement from the human sponsor: every log line must carry a file name and line number, errors must carry a stack trace, and the logger must refuse to emit values for keys that could contain secrets or PII.

## Requirements

### Functional

1. A new file `backend/RULES.md` enumerates the backend rules the scaffold follows. Sections: Layout, API, Data layer, Settings and secrets, Logging, Testing. 21 rules total. Each rule is a single declarative sentence with a one-line reason.
2. The logging stack in `backend/app/logging.py` is extended so **every** log line — from application code, FastAPI, or uvicorn — carries `filename`, `func_name`, and `lineno` fields without the caller doing anything.
3. The logging stack redacts a fixed denylist of sensitive keys (`password`, `authorization`, `token`, `cookie`, `secret`, `api_key`, `set-cookie`, `refresh_token`). Matching is case-insensitive. Redaction traverses nested dicts recursively. Lists, tuples, and sets are not traversed.
4. The demo `items` resource is reorganized into an `app/items/` domain folder containing `router.py`, `schemas.py`, `models.py`, and `service.py`. Shared infra (settings, db, redis client, logging, middleware, errors, main) stays flat at the top of `app/`.
5. The SQLAlchemy `Base` relocates from `app/models.py` to `app/db.py` (it is infra, not item-specific). `app/models.py` is deleted.
6. Alembic is configured to use a naming convention for constraints (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`) via `Base.metadata.naming_convention`. `alembic.ini`'s `file_template` yields descriptive migration filenames of the form `NNNN_<description>.py`.
7. The existing `GET /api/v1/hello` endpoint returns the same response body as before. External behavior is unchanged.
8. `docs/specs/README.md` feature roster gains a row for `feat_backend_002`.

### Non-functional

9. No new dependencies. The two logging additions use `structlog`'s existing processor APIs.
10. No enforcement of the "every log line carries a domain kwarg" rule at runtime. The rule is documented in `RULES.md` only. Forcing kwargs can push callers toward dumping full objects that leak PII, so the rule is taught, not enforced.
11. No change to the error envelope, the request-ID middleware, the `/healthz` / `/readyz` endpoints, or the versioned router mount point.
12. No linting, formatting, or pre-commit tooling introduced (per `conventions.md` §11).
13. No change to the set of migrations that exist. The naming convention applies going forward.

## User Stories

- As **Vulcan** (builder), I want a short, unambiguous rule sheet in `backend/RULES.md`, so auto-generated code for future backend features follows a consistent shape without re-deriving it from the scaffold each time.
- As a **human reviewer**, I want every log line to carry `filename`, `func_name`, `lineno`, and a stack trace when an exception is involved, so I can diagnose incidents without re-running the code.
- As a **security-minded developer**, I want the logger to silently drop sensitive values so a mistake in a `log.info(user=...)` call does not leak a password or token.
- As a **template consumer**, I want the demo `items` resource to show the target per-domain folder shape, so the first resource I add lands in the right place by copy-paste.

## Scope

### In Scope

- `backend/RULES.md`: new file, ~200 lines.
- `backend/app/logging.py`: two processor additions; public API (`configure_logging`, `get_logger`) unchanged.
- `backend/app/items/`: new directory with `__init__.py`, `router.py`, `schemas.py`, `models.py`, `service.py`.
- `backend/app/db.py`: accept `Base` relocation and set `naming_convention` on its metadata.
- `backend/app/models.py`: deleted.
- `backend/app/schemas.py`: `HelloResponse` moved out to `app/items/schemas.py`; shared schemas remain.
- `backend/app/api/v1/__init__.py`: re-point import to `app.items.router`.
- `backend/app/api/v1/hello.py`: deleted.
- `backend/alembic.ini`: updated `file_template`.
- `backend/alembic/env.py`: wires `Base.metadata.naming_convention` onto `target_metadata`.
- `backend/tests/`: update imports; add `test_logging_callsite.py`, `test_logging_redaction.py`.
- `docs/specs/README.md`: add `feat_backend_002` roster row.

### Out of Scope

- Any new endpoint, domain, or business feature.
- Any change to the error envelope, request-ID behavior, or middleware order.
- Linting, formatting, pre-commit, CI/CD (deferred per `conventions.md` §11).
- Request/response body logging, log sampling, log rotation.
- A `get_logger` wrapper, a forced-kwargs enforcement processor, or any other call-site ergonomics layer.
- Rewriting historical alembic migration files.
- Authentication, authorization, rate limiting.

## Acceptance Criteria

- [ ] `backend/RULES.md` exists and covers all six sections with the 21 rules listed in the design spec.
- [ ] `backend/app/logging.py` configures `structlog.processors.CallsiteParameterAdder` to emit `filename`, `func_name`, `lineno` on every log line.
- [ ] `backend/app/logging.py` installs a `redact_sensitive` processor that replaces denylisted keys (case-insensitive) with `"***"` at every depth within nested dicts; lists, tuples, and sets are not traversed.
- [ ] `backend/app/items/` contains `__init__.py`, `router.py`, `schemas.py`, `models.py`, `service.py`. No other files exist under `app/items/`.
- [ ] `backend/app/models.py` and `backend/app/api/v1/hello.py` are removed from the repo.
- [ ] `Base` lives in `backend/app/db.py` and sets `naming_convention` on its metadata.
- [ ] `GET /api/v1/hello` returns a response body identical to the pre-change version.
- [ ] `backend/alembic.ini`'s `file_template` produces migration filenames like `0042_<description>.py`.
- [ ] `backend/alembic/env.py` uses `Base.metadata` (which now carries the naming convention) as `target_metadata`.
- [ ] `uv run pytest` from `backend/` passes, including the two new logging tests.
- [ ] `docs/specs/README.md` has a new row for `feat_backend_002`.
- [ ] Feature status lifecycle advances `Planned` → `In Spec` (this PR) → `Ready` (on merge).
