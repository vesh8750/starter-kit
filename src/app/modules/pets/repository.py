"""Data access for pets.

A concrete, per-feature repository -- not a generic ``BaseRepository[T]``. Generic CRUD
bases look economical and then fight every real query: they push callers back to raw
SQLAlchemy for anything interesting while still forcing indirection on the simple cases.
A handful of explicit, typed methods per feature reads better and stays honest.

The repository never commits. The request-scoped session owns the transaction boundary
(see :mod:`app.db.session`), so a service can call several repositories and still get a
single atomic unit of work.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, SortParams, paginate
from app.modules.pets.models import Pet
from app.modules.pets.schemas import PetFilters

SORTABLE_FIELDS = ("created_at", "updated_at", "name", "date_of_birth")
DEFAULT_SORT = "-created_at"

_SORT_COLUMNS = {
    "created_at": Pet.created_at,
    "updated_at": Pet.updated_at,
    "name": Pet.name,
    "date_of_birth": Pet.date_of_birth,
}


class PetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, pet_id: uuid.UUID) -> Pet | None:
        return await self._session.get(Pet, pet_id)

    async def get_for_update(self, pet_id: uuid.UUID) -> Pet | None:
        """Load a row and hold a write lock on it until the transaction ends.

        Required for any read-decide-write sequence. Without the lock, two concurrent
        requests both read `status = available`, both decide the reservation is legal,
        and both write -- the second silently overwrites the first instead of getting a
        conflict. The lock is released by the request's commit or rollback.
        """
        return await self._session.get(Pet, pet_id, with_for_update=True)

    async def list(
        self,
        *,
        filters: PetFilters,
        page: PageParams,
        sort: SortParams,
    ) -> tuple[Sequence[Pet], int]:
        stmt = sort.apply(
            self._apply_filters(select(Pet), filters),
            _SORT_COLUMNS,
            tiebreaker=Pet.id,  # UUIDv7: unique *and* time-ordered, so it is a sane last key
        )
        return await paginate(self._session, stmt, page)

    def add(self, pet: Pet) -> Pet:
        """Stage an insert. Flushed by the service when it needs server defaults."""
        self._session.add(pet)
        return pet

    async def delete(self, pet: Pet) -> None:
        await self._session.delete(pet)

    async def flush(self) -> None:
        """Send pending SQL so database-generated values are readable -- not a commit."""
        await self._session.flush()

    @staticmethod
    def _apply_filters(stmt: Select[tuple[Pet]], filters: PetFilters) -> Select[tuple[Pet]]:
        if filters.species is not None:
            stmt = stmt.where(Pet.species == filters.species)
        if filters.status is not None:
            stmt = stmt.where(Pet.status == filters.status)
        if filters.search:
            # ILIKE with a bound parameter: the wildcards are data, not SQL.
            pattern = f"%{filters.search}%"
            stmt = stmt.where(or_(Pet.name.ilike(pattern), Pet.breed.ilike(pattern)))
        return stmt
