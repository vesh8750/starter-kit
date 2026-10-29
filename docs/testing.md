# Testing

```bash
make test        # everything
make test-unit   # only what needs no database
make test-cov    # with coverage
```

## How the suite is set up

**Tests run against real PostgreSQL, with the real migrations applied.** A SQLite
stand-in would not exercise native enums, check constraints, `ILIKE` or timezone-aware
timestamps — precisely the things that break in production.

**Every test is isolated by a transaction, not by truncation.** Each test opens a
connection, begins a transaction, and rolls it back at the end. Application-level
`commit()` calls land on a savepoint, so the real transaction boundary is exercised
while nothing leaks between tests. This is why the suite stays fast as it grows.

Set up `pet_test` once:

```bash
createdb pet_test
```

Override the name with `TEST_DATABASE_NAME` (CI does).

## Fixtures

| Fixture | Gives you |
|---|---|
| `settings` | Session-scoped test `Settings` (test database, temp storage root) |
| `db_session` | An `AsyncSession` inside a rolled-back transaction |
| `client` | `httpx.AsyncClient` against the real ASGI app, sharing that session |

The `client` fixture overrides **only** `get_db_session`. Middleware, dependency
resolution, serialisation and exception handling are all the production code path, so
integration tests verify what a client will actually receive.

## Unit tests

For business rules. Fake the repository — it is a small protocol-shaped class, which is
exactly why services take one:

```python
class FakePetRepository:
    async def get(self, pet_id):
        return self.pets.get(pet_id)

    ...


async def test_reserving_twice_is_a_conflict():
    service = PetService(FakePetRepository({pet.id: pet}))
    await service.reserve(pet.id, owner_id=uuid4())
    with pytest.raises(PetAlreadyAdoptedError):
        await service.reserve(pet.id, owner_id=uuid4())
```

No database, no HTTP, no fixtures. If a rule is hard to test this way, it is usually in
the wrong layer.

## Integration tests

```python
async def test_reservation_conflict_returns_409(client: AsyncClient):
    pet = await create_pet(client)
    await client.post(f"/api/v1/pets/{pet['id']}/reservation?owner_id={uuid4()}")
    response = await client.post(f"/api/v1/pets/{pet['id']}/reservation?owner_id={uuid4()}")
    assert response.status_code == 409
    assert response.json()["code"] == "pet_already_adopted"
```

Assert on the **error `code`**, not on the human-readable `detail` — the code is the
contract, the detail is prose.

Async tests need no decorator (`asyncio_mode = "auto"`).

## Conventions

* Test names state the behaviour: `test_empty_patch_is_rejected`, not `test_patch_2`.
* Build objects with `tests/factories.py` and state only the fields the test cares about.
* Test behaviour a client can observe, not internal calls. Do not assert that a
  repository method was called; assert what was persisted or returned.
* `filterwarnings = ["error"]` — a new deprecation warning fails the build rather than
  accumulating silently.
* Mark database-backed tests `@pytest.mark.integration` so `make test-unit` can skip them.

## What the suite deliberately covers

Some tests exist because a real defect got past review once. They assert the *reason*,
not just the behaviour, so the next person learns why the constraint exists:

* `test_transaction_boundary.py` — a commit failure must not return `200 OK`.
* `test_security_boundaries.py` — 401 vs 403, token forgery, body size limits, and that
  error responses leak nothing.
* `test_pagination_is_stable_when_the_sort_key_has_duplicates` — paging must not repeat
  or skip rows.
* `test_upload_extension_comes_from_the_content_type` — a lying client must not control
  the stored extension.
* `test_reserve_locks_the_row_before_deciding` — read-decide-write must lock.

## What to test

| Worth testing | Not worth testing |
|---|---|
| Business rules and their edge cases | That FastAPI validates an `int` |
| Error codes and status codes | That SQLAlchemy can insert a row |
| Filtering, sorting, pagination boundaries | Getters and setters |
| Authorisation: who is refused | Framework behaviour |
| Anything a bug report was filed about | Coverage for its own sake |
