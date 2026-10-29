# pet — backend

A production-grade FastAPI foundation: async SQLAlchemy 2, Alembic, structured logging,
RFC 9457 errors, request correlation, metrics, health checks, pluggable storage and
cache, and a strict quality gate.

The `pets` module is a complete worked example of the intended feature pattern.

---

## Quickstart

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/) and a running PostgreSQL 16+.

```bash
cp .env.example .env          # then set DATABASE_URL for your machine
createdb pet_dev && createdb pet_test
make install                  # venv + dependencies + git hooks
make migrate                  # apply migrations
make dev                      # http://127.0.0.1:8000/docs
```

Verify everything:

```bash
make check                    # format, lint, mypy --strict, tests
```

## Common commands

| Command | What it does |
|---|---|
| `make dev` | Run the API with autoreload |
| `make test` | Full test suite |
| `make test-unit` | Only tests that need no database |
| `make check` | Everything CI runs |
| `make migration m="add orders"` | Autogenerate a migration |
| `make migrate` / `make downgrade` | Apply / roll back migrations |
| `make db-reset` | Drop, recreate and migrate the dev database |
| `make docker-up` | Full local stack in Docker |
| `make help` | List all targets |

## Project layout

```
src/app/
  main.py            create_app() — the application factory
  lifespan.py        startup/shutdown for process-wide resources
  api/
    deps.py          shared dependencies (DbSession, Pagination, CurrentPrincipal, ...)
    v1/              version router; mounts module routers
  core/              cross-cutting infrastructure
    config.py        typed settings (the only place env vars are read)
    errors.py        the AppError hierarchy
    exception_handlers.py   exceptions -> RFC 9457 responses
    logging.py       structlog setup
    context.py       request id / principal context vars
    pagination.py    PageParams, SortParams, Page[T], paginate()
    security.py      password hashing + JWT primitives
    responses.py     orjson response classes
    openapi.py       OpenAPI customisation
    middleware/      request context, security headers, ordering
  db/
    base.py          DeclarativeBase, naming conventions, mixins
    session.py       engine, session dependency, transaction boundary
    types.py         reusable column types
    registry.py      model imports for Alembic
  modules/           ← feature slices live here
    pets/            reference implementation
  cache/             Cache protocol + memory/redis backends
  storage/           FileStorage protocol + local backend
  integrations/      outbound HTTP clients (ServiceClient base)
  observability/     health checks, Prometheus metrics
migrations/          Alembic
tests/
  unit/              no database
  integration/       real ASGI stack + real Postgres
docs/                architecture, workflows, ADRs
```

## Documentation

| Document | Read it when |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Understanding how the pieces fit and why |
| [docs/adding-a-feature.md](docs/adding-a-feature.md) | **Building anything new** |
| [docs/configuration.md](docs/configuration.md) | Adding or changing settings |
| [docs/database.md](docs/database.md) | Models, migrations, transactions |
| [docs/testing.md](docs/testing.md) | Writing tests |
| [docs/operations.md](docs/operations.md) | Deploying and running it |
| [docs/adr/](docs/adr/) | Why a specific decision was made |
