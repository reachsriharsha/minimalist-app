# Design: Backend rules and logging discipline

## Approach

Three disjoint pieces of work, landing in one build:

1. **Write the rules** — a new `backend/RULES.md` with six sections and 19 declarative rules, each paired with a one-line reason. The file is read by humans, Atlas, and Vulcan.
2. **Enforce the one non-negotiable rule at the logger, not at the call site** — add two processors to `app/logging.py`: `CallsiteParameterAdder` for filename/func/line, and a small `redact_sensitive` processor for secret keys. No caller changes. No wrapper. No forced-kwargs rule at runtime.
3. **Make the scaffold match its own rules** — convert the `items` demo from flat files (`app/models.py`, `app/schemas.py`, `app/api/v1/hello.py`) into `app/items/{router,schemas,models,service}.py`. Move `Base` to `app/db.py`. Wire the alembic naming convention. Touch nothing else.

The three pieces are deliberately decoupled so a regression in one does not block the others: a typo in `RULES.md` does not affect logging, a bug in the redactor does not affect the `items` move, and the `items` move is a pure refactor (`GET /api/v1/hello` returns the same bytes).

## Files to Create

| Path                                                   | Purpose                                                                 |
|--------------------------------------------------------|-------------------------------------------------------------------------|
| `backend/RULES.md`                                     | The 19-rule backend rule sheet.                                         |
| `backend/app/items/__init__.py`                        | Re-exports `router`.                                                    |
| `backend/app/items/router.py`                          | `GET /hello` route; thin, delegates to `service`.                        |
| `backend/app/items/schemas.py`                         | `HelloResponse` (moved from `app/schemas.py`).                           |
| `backend/app/items/models.py`                          | `Item` ORM (moved from `app/models.py`).                                 |
| `backend/app/items/service.py`                         | `get_seed_item(session)`, `increment_hello_counter(redis)`.              |
| `backend/tests/test_logging_callsite.py`               | Verifies callsite info is emitted.                                       |
| `backend/tests/test_logging_redaction.py`              | Verifies the redactor's four cases.                                      |

## Files to Modify

| Path                                                   | Change                                                                  |
|--------------------------------------------------------|-------------------------------------------------------------------------|
| `backend/app/logging.py`                               | Add `CallsiteParameterAdder` and `redact_sensitive` to the processor chain. |
| `backend/app/db.py`                                    | Declare `Base(DeclarativeBase)` here. Set `metadata.naming_convention`. |
| `backend/app/schemas.py`                               | Remove `HelloResponse` (moved). Keep `HealthResponse`, `ReadinessResponse`, `DependencyCheck`, `ErrorBody`, `ErrorEnvelope`. |
| `backend/app/api/v1/__init__.py`                       | Import `router` from `app.items.router` instead of `app.api.v1.hello`.   |
| `backend/alembic.ini`                                  | Change `file_template` to `%%(rev)s_%%(slug)s`.                          |
| `backend/alembic/env.py`                               | Import `Base` from `app.db` (unchanged logic; path only).                |
| `backend/tests/test_hello.py`                          | Update imports to `app.items.*`. No assertion changes.                  |
| `docs/specs/README.md`                                 | Add roster row for `feat_backend_002`.                                   |

## Files to Delete

| Path                                                   | Reason                                                                  |
|--------------------------------------------------------|-------------------------------------------------------------------------|
| `backend/app/models.py`                                | `Base` moves to `app/db.py`; `Item` moves to `app/items/models.py`.      |
| `backend/app/api/v1/hello.py`                          | Replaced by `app/items/router.py`.                                       |

## `backend/RULES.md` — content

Six sections. Each rule has a one-line *why*. No rule without a reason.

### 1. Layout

- **Domain folder per business resource**: `app/<domain>/{router,schemas,models,service}.py`. Add `dependencies.py`, `constants.py`, `exceptions.py` only when non-trivial. *Why: keeps a feature's surface area readable in one folder.*
- **Shared infra stays flat** at `app/`: `settings.py`, `db.py`, `redis_client.py`, `logging.py`, `middleware.py`, `errors.py`, `main.py`. *Why: these are not owned by any one domain.*
- **Absolute imports only** (`from app.items.service import ...`). *Why: absolute paths survive file moves; relative paths do not.*

### 2. API

- **Every business route mounts under `/api/v<N>/`**. Health and readiness stay unversioned. *Why: versioning is a guarantee to clients; infra probes are not.*
- **Every route declares `response_model=...`** and an explicit `status_code` when non-200. *Why: OpenAPI docs and client generators rely on both.*
- **URLs are RESTful**: plural nouns, no verbs in paths. Validation lives in pydantic schemas and `Depends(...)` helpers, not inside handlers. *Why: handlers become thin and service code stays framework-agnostic.*
- **Use `async def` only when the route awaits I/O**; pure or blocking work uses `def` so Starlette runs it in a threadpool. *Why: blocking work on an async route blocks the whole event loop.*

### 3. Data layer

- **SQLAlchemy 2.x `select()` style only**; no legacy `Query` API. Writes wrap in `async with session.begin(): ...` or explicit `await session.commit()`. *Why: the legacy API is deprecated and the mixture is a common source of silently-uncommitted writes.*
- **Alembic metadata uses a naming convention** for constraints: `pk_<t>`, `fk_<t>_<c>_<ref>`, `uq_<t>_<c>`, `ix_<t>_<c>`, `ck_<t>_<name>`. Set on `Base.metadata.naming_convention`. *Why: without it, autogenerated migrations produce database-dependent names that differ between Postgres versions.*
- **Migration filenames are descriptive**: `alembic.ini`'s `file_template` uses `%%(rev)s_%%(slug)s`. *Why: `0042_add_item_owner.py` is greppable; `0042_abcdef.py` is not.*

### 4. Settings and secrets

- **All config reads go through `app.settings.Settings`**. No `os.environ[...]` elsewhere. *Why: a single source for defaults, validation, and documentation.*
- **Every new setting lands in `settings.py` and `.env.example` in the same commit**. *Why: `.env.example` is the onboarding document.*
- **No secrets in the repo.** `.env` is gitignored; `.env.example` holds safe dev defaults only. *Why: git history is forever.*

### 5. Logging

- **Every log line carries** `timestamp`, `level`, `event`, `filename`, `func_name`, `lineno`, and `request_id` (when in a request). Enforced by the logger config. *Why: a log without a source location is useless during an incident.*
- **Every log line should carry at least one domain kwarg** (`item_id=...`, `user_id=...`). Rule only, not enforced. *Why: forcing kwargs can push callers toward dumping full objects that leak PII.*
- **On caught exceptions, use** `log.exception("event_name", **data)` or `log.error("event_name", exc_info=exc, **data)`. Never stringify the exception into the event name or a message. *Why: `exc_info` preserves the full traceback; a stringified exception loses the frames.*
- **Never log secrets or PII.** The logger redacts a fixed denylist (`password`, `authorization`, `token`, `cookie`, `secret`, `api_key`, `set-cookie`, `refresh_token`). Extending the denylist is a one-line change in `app/logging.py`. *Why: a mistake in a single call site should not leak a credential.*
- **Event names are snake_case noun phrases** (`item_fetched`, `redis_incr_failed`). Not sentences, not verbs. *Why: event names are indexed; consistent shapes are searchable.*
- **No `print()`.** Anywhere. *Why: `print` bypasses the structured formatter and the redactor.*

### 6. Testing

- **`pytest` + `httpx.AsyncClient` + `pytest-asyncio`.** Tests needing Postgres or Redis skip with a clear reason when unreachable. *Why: a bare `pytest` run succeeds without any external service running.*
- **One test file per domain router**; shared fixtures in `backend/tests/conftest.py`. *Why: a failing test points at its domain.*

## Data flow

External behavior is unchanged. The `GET /api/v1/hello` request now traces through:

```
client
  → RequestIDMiddleware       (binds request_id into structlog contextvars)
  → ExceptionEnvelopeMiddleware
  → FastAPI routing: /api/v1/hello
  → app.items.router.hello    (thin: resolves deps, calls service)
     ├── app.items.service.get_seed_item(session) — reads items.id=1
     └── app.items.service.increment_hello_counter(redis) — INCR hello:count
  → HelloResponse
  → response with X-Request-ID header
```

The `router` function signature and response body are byte-for-byte identical to the pre-change `app/api/v1/hello.py`.

## Logging processor chain (exact order)

Current order in `app/logging.py` (before this feature):

```
merge_contextvars → add_log_level → TimeStamper → StackInfoRenderer
                                                 → format_exc_info
                                                 → JSONRenderer
```

New order:

```
merge_contextvars
  → add_log_level
  → TimeStamper
  → CallsiteParameterAdder(FILENAME, FUNC_NAME, LINENO)
  → StackInfoRenderer
  → redact_sensitive
  → format_exc_info
  → JSONRenderer
```

`CallsiteParameterAdder` runs before `StackInfoRenderer` because later processors may mutate the event dict, but none of them move the frame pointer; it is safe anywhere in the chain in practice. We place it early so its output is visible to everything else.

`redact_sensitive` runs after `StackInfoRenderer` but before `format_exc_info`. Reason: stack-info rendering adds a `stack` string; we do not redact traceback frames (they are not keyed user data). `format_exc_info` produces a rendered traceback string; redacting after it would require substring scanning, which is out of scope.

## `redact_sensitive` — exact implementation

```python
_SENSITIVE_KEYS = frozenset({
    "password",
    "authorization",
    "token",
    "cookie",
    "secret",
    "api_key",
    "set-cookie",
    "refresh_token",
})


def _redact(value):
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in value.items()
        }
    return value


def redact_sensitive(_logger, _method_name, event_dict):
    return {
        k: ("***" if k.lower() in _SENSITIVE_KEYS else _redact(v))
        for k, v in event_dict.items()
    }
```

Contract:

- Top-level keys are scrubbed.
- Nested dicts are scrubbed recursively: every dict value that is itself a dict is walked with the same rules, at any depth.
- Lists, tuples, and sets are **not** traversed. A log line that passes a list of user dicts is a design error the rules document calls out.
- Non-string keys are left as-is (`k.lower()` would fail on a non-string key, which shouldn't happen in structlog-land).
- Matching is case-insensitive via `.lower()`.
- The denylist is a module-level `frozenset` so extension is a one-line change.

## Domain move — `app/items/`

### `app/items/__init__.py`

```python
from app.items.router import router

__all__ = ["router"]
```

### `app/items/models.py`

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
```

### `app/items/schemas.py`

```python
from pydantic import BaseModel


class HelloResponse(BaseModel):
    message: str
    item_name: str
    hello_count: int
```

### `app/items/service.py`

```python
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.items.models import Item

HELLO_COUNTER_KEY = "hello:count"


async def get_seed_item(session: AsyncSession) -> Item | None:
    result = await session.execute(select(Item).where(Item.id == 1))
    return result.scalar_one_or_none()


async def increment_hello_counter(redis: Redis) -> int:
    return int(await redis.incr(HELLO_COUNTER_KEY))
```

### `app/items/router.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.items import service
from app.items.schemas import HelloResponse
from app.redis_client import get_redis

router = APIRouter(tags=["items"])


@router.get("/hello", response_model=HelloResponse)
async def hello(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HelloResponse:
    item = await service.get_seed_item(session)
    if item is None:
        raise HTTPException(
            status_code=503,
            detail="seed item missing; run 'alembic upgrade head'",
        )
    count = await service.increment_hello_counter(redis)
    return HelloResponse(
        message="hello from minimalist-app",
        item_name=item.name,
        hello_count=count,
    )
```

### `app/db.py` — `Base` relocation

The existing `db.py` exposes `build_engine`, `build_sessionmaker`, `get_session`. Add:

```python
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING_CONVENTION
```

`app/models.py` is removed. Any import of `from app.models import Base` is rewritten to `from app.db import Base`. `alembic/env.py` picks up `Base.metadata` from its new home; the naming convention rides on the metadata instance, so autogenerated migrations from now on produce deterministic constraint names.

## Alembic `file_template`

Current (default) template in `alembic.ini` produces `<rev>_.py`. Change to:

```
file_template = %%(rev)s_%%(slug)s
```

which produces `0042_add_item_owner.py` when the `message` passed to `alembic revision -m "add item owner"` is slugified.

## Edge cases and risks

- **Structlog processor ordering**: the redactor must run before any processor that flattens `exc_info` into a string, or we lose the chance to scrub traceback-adjacent kwargs. Ordering is pinned above.
- **Non-string log kwargs**: a caller could pass `{1: "secret"}` as a kwarg value. `_redact` handles it: `1` is not a string, so `k.lower()` is never called on it; the value recurses safely.
- **Keys in upper-case**: `Authorization` and `AUTHORIZATION` both scrub because matching is on `.lower()`.
- **Nested lists of dicts**: not scrubbed. This is called out in `RULES.md`; a line that logs a list of user dicts is a smell regardless.
- **Deeply nested dicts**: walked recursively with no depth cap. At template scale log events are small; a pathological deeply-nested event would be a separate bug worth catching. If this ever becomes a real concern, cap the recursion at a fixed depth in one place (`_redact`).
- **Alembic naming convention applied retroactively**: it is **not**. Existing migrations keep their auto-generated names. Only new migrations pick up the convention. Dropping a constraint from the existing table would still use the original name — which is fine, because alembic uses the DB-side name, not the convention.
- **Domain move in flight with another feature**: the `items` conversion is mechanical and affects three files (`app/models.py`, `app/schemas.py`, `app/api/v1/hello.py`). If another in-flight branch touches any of these, the rebase is likely to be a clean conflict (delete-vs-edit).
- **Test-suite regression from import changes**: `backend/tests/test_hello.py` is the only test file that imports from the moved modules; its updates are mechanical.

## Security considerations

- The redactor is **defense in depth**, not a primary control. `RULES.md` still says: do not log secrets.
- The denylist is intentionally short and literal. A smarter (regex-based) matcher would introduce its own false-positive / false-negative failure modes. Keep it obvious.
- Logs go to stdout. Infra (docker-compose today; a real log collector later) decides what happens after that. This feature does not touch that boundary.
- No log-injection hardening (CR/LF scrubbing in log values) is added. `JSONRenderer` escapes control characters in strings, which covers the common case.

## Open questions

None at spec time. Decisions already closed in brainstorming:

- Option B runtime (callsite + redactor; no kwargs-empty enforcement).
- Option B layout (domain-driven now; rewrite items demo).
- Atlas-only spec PR; Vulcan in a later session.
