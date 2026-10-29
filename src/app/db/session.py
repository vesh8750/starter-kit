"""Engine, session factory and the transaction boundary.

**The rule: one request, one session, one transaction.**

The :data:`DbSession` dependency opens a session, hands it to the endpoint, and commits
when the endpoint returns normally -- or rolls back if anything was raised. Services
therefore never call ``commit()``; a request either applies fully or not at all, which
removes a whole class of half-written-state bugs.

**``scope="function"`` is load-bearing, not decoration.** FastAPI closes ordinary
(request-scoped) ``yield`` dependencies *after* the response has already been sent, so a
failure at commit time -- a unique violation, a deferred constraint, a serialisation
failure, a connection lost mid-commit -- could not alter the response. The client would
receive ``200 OK`` with a success body while the transaction was rolled back and nothing
was persisted: silent data loss reported as success. Function-scoped dependencies are
torn down *before* the response is sent, so the commit failure becomes a real 409/503
through the normal exception handlers.

Consequence to respect: anything that must run *after* the response (a background task)
cannot use this session -- it is already closed. Use :func:`session_scope`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.errors import ConflictError, ServiceUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, Any] = {
        "timeout": settings.database_pool_timeout_seconds,
        # Server-side statement timeout: a runaway query cannot hold a connection
        # (and the request behind it) open indefinitely.
        "server_settings": {
            "application_name": f"{settings.project_name}-{settings.environment}",
            "statement_timeout": str(settings.database_statement_timeout_ms),
        },
    }
    return create_async_engine(
        settings.database_url_str,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_pre_ping=True,  # survives database restarts and idle-connection reaping
        pool_recycle=1800,
        connect_args=connect_args,
    )


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide engine. Called once from the application lifespan."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(settings)
        _session_factory = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,  # instances stay usable while the response serialises
            autoflush=True,
        )
        log.info("db.engine_initialised", pool_size=settings.database_pool_size)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        log.info("db.engine_disposed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialised; call init_engine() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Session factory is not initialised; call init_engine() first.")
    return _session_factory


def translate_database_error(exc: Exception) -> Exception:
    """Map driver errors onto the application error model.

    Integrity violations are a client-visible conflict, not a server fault; connection
    failures are a 503. Anything else is left alone and becomes a logged 500.
    """
    if isinstance(exc, IntegrityError):
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        return ConflictError(
            "The request conflicts with existing data.",
            extra={"constraint": constraint} if constraint else None,
        )
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return ServiceUnavailableError("The database is temporarily unavailable.")
    return exc


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Standalone transactional session for code outside the request cycle."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise translate_database_error(exc) from exc
    finally:
        await session.close()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Per-request session. Commits on success, rolls back on failure.

    Always consumed through :data:`DbSession`, which pins it to ``scope="function"``.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise translate_database_error(exc) from exc
    finally:
        await session.close()


# scope="function" -> torn down before the response is sent. See the module docstring;
# removing it reintroduces "commit failed but the client got 200".
DbSession = Annotated[AsyncSession, Depends(get_db_session, scope="function")]
