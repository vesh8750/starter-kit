# Database, migrations and transactions

PostgreSQL 16+ with SQLAlchemy 2 (async, `asyncpg`) and Alembic.

## Sessions and transactions

**One request, one session, one transaction.**

```python
@router.post("")
async def create_thing(
    payload: ThingCreate, session: DbSession
) -> ThingRead: ...  # commits automatically when this returns
```

`DbSession` commits on success and rolls back if anything raises. Consequences worth
internalising:

* **Services never call `commit()`.** If they did, a later failure in the same request
  could not roll the earlier work back.
* **A request is atomic.** Multiple repositories, multiple tables, one unit of work.
* **Use `flush()`, not `commit()`,** when you need a generated id or timestamp before
  returning.

Outside a request — background tasks, CLI commands, scheduled jobs — open your own:

```python
async with session_scope() as session:
    ...
```

Driver errors are translated by `translate_database_error()`: an integrity violation
becomes a 409 `conflict`, a lost connection becomes a 503. Everything else stays a
logged 500.

### Locking

Any rule of the form "only allowed if the current state is X" is a read-decide-write
sequence and races without a row lock:

```python
pet = await self._repository.get_for_update(pet_id)  # SELECT ... FOR UPDATE
if pet.status is not AdoptionStatus.AVAILABLE:
    raise PetAlreadyAdoptedError(...)
```

Without the lock, two concurrent requests both read `available`, both decide the write
is legal, and the second silently overwrites the first. The lock is held until the
request's commit or rollback.

### Savepoints

For a sub-operation that may fail without losing the whole request:

```python
async with session.begin_nested():
    session.add(optional_thing)
```

## Models

Inherit from `Base` plus the mixins you need:

```python
class Thing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "things"
```

* **UUIDv7 primary keys** — opaque like UUIDv4, but time-ordered, so inserts do not
  fragment the index.
* **Timestamps are database-generated** (`now()`), consistent across instances.
  `Base` sets `eager_defaults=True` so those values come back via `RETURNING` instead of
  triggering a lazy (and under asyncio, *illegal*) refresh after a flush.
* **`SoftDeleteMixin` is opt-in.** Every query on that table then has to filter
  `deleted_at IS NULL`; only pay that price where recovery is a real requirement.
* **Enums:** always `enum_column(MyEnum, "my_enum")`. Plain `Enum(MyEnum)` persists
  member *names* (`DOG`), which silently disagrees with what the API serialises.
* **Models are discovered automatically** by `db/registry.py` — no import list to
  maintain. That list used to be manual, and a missing line produced an empty migration
  *and* a passing `alembic check`, so the table silently never existed.
* **Constraint names** come from the naming convention in `db/base.py`. Never rely on
  server-generated names — Alembic cannot drop what it cannot name.

## Migrations

```bash
make migration m="add orders table"   # autogenerate
make migrate                          # upgrade head
make downgrade                        # roll back one
```

The URL comes from `Settings`, so migrations always target the configured database.
Override it explicitly when needed: `alembic -x database_url=... upgrade head`.

### Always review the generated file

Autogenerate is a starting point, not an answer.

* **Renames are detected as drop + add**, which deletes data. Rewrite them as
  `op.alter_column(..., new_column_name=...)`.
* **Postgres enum types are not dropped on downgrade.** Add it yourself, or a
  downgrade/upgrade cycle fails with "type already exists":
  ```python
  sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
  ```
* **Adding a NOT NULL column to a populated table needs three steps**: add it nullable,
  backfill, then set NOT NULL.
* **Indexes on large tables** should use `CREATE INDEX CONCURRENTLY`, which cannot run
  inside a transaction — put it in its own migration with
  `op.get_context().autocommit_block()`.
* **Write the `downgrade()`.** CI runs `alembic downgrade base && alembic upgrade head`.

### CI guards

* `alembic check` fails if the models and migrations have diverged — the classic "changed
  a model, forgot the migration" bug.
* A full downgrade/upgrade cycle proves migrations are reversible.

### Deployment

Migrations run as a **separate, ordered step** before the new version starts — a job or
an init container, never in the application's `CMD`, which would race on every scale-up.
Keep each migration backwards-compatible with the currently running version so a rollback
does not require a database restore.

## Querying

* Use `select()` and the typed 2.0 API; avoid legacy `Query`.
* Use `paginate()` for anything that can return more than a handful of rows. It relies
  on `SortParams.apply(..., tiebreaker=Model.id)` producing a **total order** — offset
  pagination over a non-unique sort key silently repeats and skips rows.
* Guard against N+1 with `selectinload()` / `joinedload()` — lazy loading raises
  `MissingGreenlet` under asyncio rather than quietly issuing extra queries, which is a
  feature.
* Never interpolate user input into SQL. Filters and sorts use bound parameters and a
  field whitelist.
