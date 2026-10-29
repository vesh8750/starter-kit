"""Shared test fixtures.

Two properties make this suite pleasant to work in:

* **Tests run against real Postgres**, with the real migrations applied. An in-memory
  SQLite stand-in would not exercise enums, check constraints, ``ILIKE`` or timezone-aware
  timestamps -- exactly the things that break in production.
* **Every test is perfectly isolated and fast.** Each test runs inside a transaction that
  is rolled back at the end, rather than truncating tables. Nested ``commit()`` calls from
  application code land on a savepoint, so the request-level commit is genuinely
  exercised without leaking data between tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from alembic import command
from alembic.config import Config

from app.cache.factory import dispose_cache, init_cache
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine, get_db_session, init_engine
from app.main import create_app
from app.storage.factory import init_storage, reset_storage


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Test settings: the test database and a throwaway storage root."""
    get_settings.cache_clear()
    base = str(get_settings().database_url).rsplit("/", 1)[0]
    test_db = os.getenv("TEST_DATABASE_NAME", "pet_test")
    return Settings(
        environment="test",
        database_url=f"{base}/{test_db}",
        cache_backend="memory",
        storage_backend="local",
        storage_local_path=tmp_path_factory.mktemp("uploads"),
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def _migrated_database(settings: Settings) -> None:
    """Apply the real migration chain once per session."""
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url_str.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def _engine(settings: Settings, _migrated_database: None) -> AsyncIterator[AsyncEngine]:
    """The application's own engine, so health checks and tests share one pool."""
    engine = init_engine(settings)
    yield engine
    await dispose_engine()


@pytest.fixture
async def db_session(_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is always rolled back."""
    connection = await _engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
async def client(settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app, sharing the test's rolled-back session.

    Only ``get_db_session`` is overridden -- everything else (middleware, exception
    handlers, serialisation) is the production code path, so these are real integration
    tests rather than tests of a parallel wiring.
    """
    init_cache(settings)
    init_storage(settings)
    app = create_app(settings)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        # Mirrors the real dependency's commit-on-success semantics so that tests
        # exercise the actual transaction boundary. The commit lands on a savepoint
        # inside the test's outer transaction, which is rolled back afterwards.
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()

    app.dependency_overrides[get_db_session] = _session_override
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    app.dependency_overrides.clear()
    await dispose_cache()
    reset_storage()
