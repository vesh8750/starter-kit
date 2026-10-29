"""Health endpoints.

Three distinct questions, three endpoints -- conflating them is what causes orchestrators
to restart healthy pods during a database blip:

* ``/health/live``  -- is the process alive? No dependencies checked. Never fails while
  the event loop runs, so a liveness probe never restarts a process over a downstream fault.
* ``/health/ready`` -- can this instance serve traffic? Checks dependencies; a failure
  removes the instance from the load balancer until it recovers.
* ``/health``       -- human-facing summary with version and per-check detail.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_engine

log = get_logger(__name__)
router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "degraded", "failed"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str | None = None
    duration_ms: float | None = None


class HealthResponse(BaseModel):
    status: CheckStatus
    version: str
    environment: str
    checks: dict[str, dict[str, object]] = {}


async def check_database() -> CheckResult:
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        async with asyncio.timeout(2.0):
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("health.database_check_failed", error=str(exc))
        return CheckResult("database", "failed", detail=type(exc).__name__)
    return CheckResult("database", "ok", duration_ms=round((loop.time() - started) * 1000, 2))


# Register additional readiness probes here (cache, required upstream APIs, ...).
# Keep them cheap and time-bounded: a readiness endpoint that hangs is worse than one
# that reports failure.
READINESS_CHECKS: list[Callable[[], Awaitable[CheckResult]]] = [check_database]


async def _run_checks() -> list[CheckResult]:
    return list(await asyncio.gather(*(check() for check in READINESS_CHECKS)))


def _aggregate(results: list[CheckResult]) -> CheckStatus:
    if any(r.status == "failed" for r in results):
        return "failed"
    if any(r.status == "degraded" for r in results):
        return "degraded"
    return "ok"


@router.get("/health/live", summary="Liveness probe", response_model=HealthResponse)
async def live() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", version=__version__, environment=settings.environment)


@router.get("/health/ready", summary="Readiness probe", response_model=HealthResponse)
async def ready(response: Response) -> HealthResponse:
    settings: Settings = get_settings()
    results = await _run_checks()
    overall = _aggregate(results)
    if overall == "failed":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=overall,
        version=__version__,
        environment=settings.environment,
        checks={r.name: {"status": r.status, "detail": r.detail} for r in results},
    )


@router.get("/health", summary="Health summary", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    return await ready(response)
