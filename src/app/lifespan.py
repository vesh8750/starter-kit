"""Application startup and shutdown.

All process-wide resources are created here and torn down in reverse. Nothing is created
lazily at first use: a misconfigured database URL or an unreachable Redis should fail the
deploy at startup, not the first customer request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.cache.factory import dispose_cache, init_cache
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import dispose_engine, init_engine
from app.storage.factory import init_storage, reset_storage

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Set by create_app; falling back to get_settings() only for an app built by hand.
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    log.info(
        "app.starting",
        version=__version__,
        environment=settings.environment,
        debug=settings.debug,
    )

    init_engine(settings)
    init_cache(settings)
    init_storage(settings)

    if settings.environment.is_deployed and settings.cache_backend == "memory":
        # Same class of trap as local storage: correct on one process, quietly
        # inconsistent behind a load balancer, and invisible until a cached value
        # matters. Warn rather than fail -- single-process deployments are legitimate.
        log.warning(
            "cache.memory_backend_in_deployed_environment",
            detail="Each worker holds its own cache; entries are not shared between them.",
        )

    if settings.environment.is_deployed and settings.storage_backend == "local":
        # Not fatal -- a single-node deployment is legitimate -- but silently losing
        # uploads on the next redeploy is not something to discover from a user report.
        log.warning(
            "storage.local_backend_in_deployed_environment",
            detail="Uploads are not shared between replicas and are lost on redeploy.",
        )

    log.info("app.started")
    try:
        yield
    finally:
        log.info("app.stopping")
        await dispose_cache()
        await dispose_engine()
        reset_storage()
        log.info("app.stopped")
