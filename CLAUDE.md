# CLAUDE.md

Guidance for AI assistants working in this repository. Read this before making changes.

## What this is

A FastAPI backend foundation. The `pets` module is a **reference example** of the
intended pattern, not a product feature — copy its shape when adding real features.

Stack: Python 3.13 · FastAPI · SQLAlchemy 2 (async, asyncpg) · PostgreSQL · Alembic ·
Pydantic v2 · structlog · uv · ruff · mypy (strict) · pytest.

## Before you finish

Always run and fix:

```bash
make check      # ruff format + ruff check + mypy --strict + pytest
```

Do not report work as complete until this passes. If you changed a model, also run
`make migration m="..."` and review the generated file.

## Where code goes

| Adding | Goes in |
|---|---|
| A feature (endpoints + rules + tables) | `src/app/modules/<feature>/` — copy `pets/` |
| Something two features would both need | `src/app/core/` |
| An external API client | `src/app/integrations/<service>.py`, subclassing `ServiceClient` |
| A config value | `src/app/core/config.py` **and** `.env.example` |
| A model | the module's `models.py` (discovered automatically by `db/registry.py`) |
| A route | the module's `router.py`, **plus an include in `src/app/api/v1/__init__.py`** |

Full walkthrough: [docs/adding-a-feature.md](docs/adding-a-feature.md).

## Rules that matter

1. **Never call `session.commit()`** in a service or repository. The request owns the
   transaction (`DbSession` commits on success). Use `flush()` for generated values.
   `DbSession` is `scope="function"` on purpose — see [ADR 0003](docs/adr/0003-transaction-boundary.md).
   Do not "simplify" that away; request scope makes commit failures return `200 OK`.
2. **Never raise `HTTPException`** in business code. Raise an `AppError` subclass from
   `core/errors.py`; the handlers render it. Note the name is `InputValidationError`,
   not `ValidationError` — that one is Pydantic's.
   **Never raise from pure-ASGI middleware either**: it sits outside the handlers, so it
   must render its own problem+json response (see `core/middleware/body_limit.py`).
3. **Never read `os.environ`.** Add a field to `Settings` and use `get_settings()`.
4. **Never `print()` or use `logging.getLogger`.** Use
   `log = get_logger(__name__)` and `log.info("event.name", key=value)` — event names
   with fields, not interpolated strings.
5. **Never store a file path or URL on a model.** Store the storage key from
   `FileStorage`; resolve with `storage.url_for(key)` in the schema's `from_model()`.
   Build keys with `build_storage_key(ns, content_type=...)` — **never** from the
   client's filename. Load the owning row *before* writing the object, and never delete
   a superseded object before the transaction commits.
6. **Never interpolate user input into SQL**, including `ORDER BY`. Use `SortParams`
   with a field whitelist.
7. **Never import another module's repository or query its tables.** Call its service.
8. **Any read-decide-write rule must lock the row** (`get_for_update`, i.e.
   `SELECT ... FOR UPDATE`). "Only allowed if the status is X" is a lost update
   without it — see `PetService.reserve`.
9. **Always use `enum_column()`** for enum columns — plain `Enum()` stores member names,
   not values.
10. **Always reuse the existing infrastructure** rather than re-solving it: pagination
   (`Page[T]`, `paginate()`), errors, logging, HTTP clients, storage, cache.
11. **Do not add a dependency** without a clear reason; prefer what is already here.

## Conventions

* Input schemas set `extra="forbid"`; separate `Create`/`Update`/`Read` models.
* PATCH bodies use `model_dump(exclude_unset=True)` so unset ≠ null.
* Routes are thin: parse, call a service, choose a status code.
* Services take and return domain objects; they never see `Request`/`Response`.
* Type annotations everywhere in `src/` — mypy runs strict and must stay clean.
* Money is integer minor units. Timestamps are timezone-aware, always UTC.
* Tests assert on error `code`, not on `detail` prose.

## Things that will bite you

* **Alembic renames** are emitted as drop + add, which loses data. Rewrite them.
* **Postgres enum types are not dropped on downgrade** — add the explicit drop.
* **Lazy loading raises `MissingGreenlet`** under asyncio. Use `selectinload()`.
* **`runtime_checkable` Protocols only check that a method *exists*** — `isinstance(x,
  SomeAsyncProtocol)` is true for sync objects too. Inspect the callable instead.
* **Background tasks must not use the request session** — it is closed before the
  response is sent. Use `session_scope()`.
* **`asyncio_default_test_loop_scope = "session"`** — session-scoped async fixtures and
  tests must share one event loop; changing this breaks the suite confusingly.

## Documentation

`docs/architecture.md` (how and why) · `docs/adding-a-feature.md` (the workflow) ·
`docs/database.md` · `docs/testing.md` · `docs/configuration.md` · `docs/operations.md` ·
`docs/adr/` (decisions, including what was deliberately left out and when to add it).

When you make a decision that a future reader would otherwise re-litigate, add an ADR.
