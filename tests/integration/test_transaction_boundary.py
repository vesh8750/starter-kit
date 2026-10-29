"""The transaction boundary must be able to fail the response.

This is the regression guard for the most dangerous bug this foundation had: FastAPI
tears down ordinary ``yield`` dependencies *after* the response has been sent, so a
failure during ``commit()`` could not change the status code. The client received
``200 OK`` with a success body while the transaction had been rolled back and nothing
was written -- silent data loss reported as success.

``DbSession`` pins the dependency to ``scope="function"``, which is torn down before the
response is sent. If anyone removes that, these tests fail.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import get_args

import pytest
from fastapi import APIRouter, Depends, params
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError
from app.db.session import DbSession, get_db_session
from app.main import create_app
from app.modules.pets.models import Pet, Species

pytestmark = pytest.mark.integration


async def test_failure_during_commit_is_reported_to_the_client(settings: Settings):
    """A dependency that fails at teardown must produce its real status, not a 200."""

    async def session_that_fails_on_commit() -> AsyncIterator[None]:
        yield None
        raise ConflictError("integrity violation surfaced at commit")

    app = create_app(settings)
    probe = APIRouter()

    @probe.get("/_probe")
    async def handler(_: None = Depends(session_that_fails_on_commit, scope="function")) -> dict:
        return {"ok": True}

    app.include_router(probe)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_probe")

    assert response.status_code == 409, "commit-time failure must not surface as 200 OK"
    assert response.json()["code"] == "conflict"


def test_db_session_dependency_is_function_scoped():
    """Guards the specific annotation, so the reason survives a refactor."""
    metadata = get_args(DbSession)[1:]
    depends = next(m for m in metadata if isinstance(m, params.Depends))
    assert depends.scope == "function", (
        "DbSession must stay scope='function'; request scope commits after the response "
        "is sent, which makes commit failures invisible to the client."
    )


async def test_integrity_error_at_commit_becomes_a_conflict(db_session: AsyncSession):
    """The real driver path: two rows with the same primary key, caught at commit."""
    duplicate_id = uuid.uuid4()
    generator = get_db_session()

    # Drive the dependency directly against the test transaction.
    session = await anext(generator)
    session.add(Pet(id=duplicate_id, name="A", species=Species.DOG))
    session.add(Pet(id=duplicate_id, name="B", species=Species.CAT))

    with pytest.raises(ConflictError) as exc_info:
        await anext(generator, None)  # triggers the commit inside the dependency

    assert exc_info.value.status_code == 409
