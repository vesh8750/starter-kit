# Adding a feature

Copy `src/app/modules/pets/` and adapt it. This document explains each step and the
handful of rules that keep slices independent.

Worked example: **adding an `orders` module.**

---

## 1. Create the slice

```
src/app/modules/orders/
    __init__.py
    models.py
    schemas.py
    repository.py
    service.py
    router.py
    exceptions.py
```

Not every file is mandatory. A module with no persistence needs no `models.py` or
`repository.py`; a module with no domain-specific failures needs no `exceptions.py`.
Do not create empty files to complete the pattern.

## 2. Model the data — `models.py`

```python
class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    reference: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, "order_status"))
    total_cents: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("total_cents >= 0", name="total_non_negative"),)
```

* Always build enum columns with `enum_column()` — plain `Enum(...)` stores member
  *names*, not values.
* Put integrity rules in the database. A `CheckConstraint` protects the data against
  every writer, including migrations and manual SQL; a Python `if` protects it against
  one code path.
* Money is an integer of minor units, never a float.

No registration step: `db/registry.py` discovers every `app.modules.*.models` package
automatically. (It used to be a manual import list — forgetting a line produced an empty
migration *and* a passing `alembic check`, so the table silently never existed.)

## 3. Generate the migration

```bash
make migration m="add orders table"
```

Read the generated file before committing. Autogenerate is a draft: it does not detect
renames (it emits drop + add, which loses data), and it does not drop Postgres enum
types on downgrade. See [database.md](database.md).

## 4. Define the contract — `schemas.py`

Separate schemas per direction: `OrderCreate`, `OrderUpdate`, `OrderRead`. Set
`extra="forbid"` on input models so a typo is a 422 rather than a silently ignored
field, and never accept a field the client should not control (status, totals, owner).

For PATCH bodies, use `model_dump(exclude_unset=True)` so "not supplied" stays
distinguishable from "set to null".

## 5. Write the queries — `repository.py`

Concrete methods, typed, one class per feature. No generic `BaseRepository[T]`.
Never call `commit()` — the request owns the transaction. Use `flush()` when you need a
database-generated value (an id, a timestamp) before returning.

Reuse `paginate()` and `SortParams` rather than hand-rolling `LIMIT`/`ORDER BY`, and
always validate sort fields against a whitelist — interpolating a client string into
`ORDER BY` is an injection vector.

## 6. Write the rules — `service.py`

This is where the feature actually lives.

```python
async def cancel(self, order_id: uuid.UUID, *, actor: Principal) -> Order:
    # _get_locked, not get: this is read-decide-write, so the row must be locked
    # or two concurrent cancellations both pass the check.
    order = await self._get_locked(order_id)
    if order.status is OrderStatus.SHIPPED:
        raise OrderAlreadyShippedError(order_id)
    order.status = OrderStatus.CANCELLED
    await self._repository.flush()
    log.info("order.cancelled", order_id=str(order_id), actor=actor.subject)
    return order
```

Services raise `AppError` subclasses, never `HTTPException`. They take and return
domain objects, not requests and responses. That is what makes them callable from a
job or a CLI command, and unit-testable with a ten-line fake repository.

## 7. Expose it — `router.py`

```python
router = APIRouter(prefix="/orders", tags=["orders"])


def get_order_service(session: DbSession) -> OrderService:
    return OrderService(OrderRepository(session))


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]


@router.post("", status_code=201, dependencies=[require_scopes("orders:write")])
async def create_order(payload: OrderCreate, service: OrderServiceDep) -> OrderRead:
    return OrderRead.model_validate(await service.create(payload))
```

Routes stay boring: parse, call, choose a status code. One `get_*_service` provider per
module gives tests a single override point.

**Mount it** in `src/app/api/v1/__init__.py`:

```python
from app.modules.orders.router import router as orders_router

api_router.include_router(orders_router)
```

## 8. Test it

* `tests/unit/test_order_service.py` — rules, with a fake repository. Fast, no database.
* `tests/integration/test_orders_api.py` — the real stack, using the `client` fixture.

Test behaviour a client can observe: status codes, error `code`s, what actually persisted.
See [testing.md](testing.md).

## 9. Verify

```bash
make check
```

---

## Recipes

### Calling an external API

Add `src/app/integrations/shipping.py`:

```python
class ShippingClient(ServiceClient):
    service_name = "shipping"

    async def quote(self, weight_kg: float) -> Quote:
        data = await self.get_json("/quotes", params={"weight": weight_kg})
        return Quote.model_validate(data)
```

Create it once in `lifespan.py`, expose it as a dependency, and inject it into the
service. Timeouts, retries on idempotent methods, error translation and request-id
propagation are inherited. Tests override the dependency with a fake — no HTTP mocking.

### Accepting an upload

Follow `PUT /pets/{pet_id}/photo`, which encodes four rules learned the hard way:

1. Validate the declared content type against an allowlist.
2. Build the key with `build_storage_key(ns, content_type=...)`. **Never** derive the
   name or extension from the client's filename — that is how `payload.html` ends up
   stored and served.
3. Load the owning row *before* writing the object, or a 404 leaves an orphan behind.
4. Do not delete a superseded object inside the request; the transaction has not
   committed. Log the key and let a sweeper reclaim it.

Body size has two limits: `MaxBodySizeMiddleware` (global, applied before anything is
buffered) and `max_bytes` (per endpoint, applied while writing). The second is not a
substitute for the first — by the time it runs the bytes have already been accepted.

### Caching an expensive read

```python
if (cached := await cache.get(key := cache_key("orders", "summary", org_id))) is not None:
    return cached
result = await expensive()
await cache.set(key, result, ttl_seconds=60)
```

Invalidate with `cache.delete(key)` or `cache.clear_prefix("orders:")` on write. Never
cache anything that must be correct rather than merely fresh.

### Doing work after the response

```python
@router.post("/{order_id}/receipt")
async def send_receipt(order_id: uuid.UUID, tasks: BackgroundTasks, ...) -> None:
    tasks.add_task(email_receipt, order_id)
```

The request's session is closed by then — the task must open its own with
`session_scope()`. If the work must survive a restart or be retried, it needs a real
queue, not a background task (see [architecture.md](architecture.md#deliberate-omissions)).

### Requiring authentication

```python
@router.get("/mine")
async def my_orders(principal: CurrentPrincipal, service: OrderServiceDep) -> Page[OrderRead]:
    ...

@router.delete("/{order_id}", dependencies=[require_scopes("orders:admin")])
```

`CurrentPrincipal` gives an authenticated caller (401 if absent); `require_scopes`
authorises (403 if under-privileged).
