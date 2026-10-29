"""Business logic for pets.

Services are where the rules live. They:

* receive validated schemas and return domain objects,
* raise :class:`~app.core.errors.AppError` subclasses instead of HTTP responses,
* never touch ``Request``, ``Response`` or status codes,
* never commit -- the request transaction does that.

That combination is what makes them directly unit-testable and reusable from a CLI
command, a scheduled job or another service without going through HTTP.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.core.logging import get_logger
from app.core.pagination import PageParams, SortParams
from app.modules.pets.exceptions import PetAlreadyAdoptedError, PetNotFoundError
from app.modules.pets.models import AdoptionStatus, Pet
from app.modules.pets.repository import PetRepository
from app.modules.pets.schemas import PetCreate, PetFilters, PetUpdate
from app.storage.base import AsyncReadable, FileStorage, build_storage_key

log = get_logger(__name__)


class PetService:
    def __init__(self, repository: PetRepository, storage: FileStorage | None = None) -> None:
        self._repository = repository
        self._storage = storage

    async def get(self, pet_id: uuid.UUID) -> Pet:
        pet = await self._repository.get(pet_id)
        if pet is None:
            raise PetNotFoundError(pet_id)
        return pet

    async def _get_locked(self, pet_id: uuid.UUID) -> Pet:
        pet = await self._repository.get_for_update(pet_id)
        if pet is None:
            raise PetNotFoundError(pet_id)
        return pet

    async def list(
        self,
        *,
        filters: PetFilters,
        page: PageParams,
        sort: SortParams,
    ) -> tuple[Sequence[Pet], int]:
        return await self._repository.list(filters=filters, page=page, sort=sort)

    async def create(self, payload: PetCreate) -> Pet:
        pet = Pet(**payload.model_dump())
        self._repository.add(pet)
        await self._repository.flush()  # populate id / created_at for the response
        log.info("pet.created", pet_id=str(pet.id), species=pet.species.value)
        return pet

    async def update(self, pet_id: uuid.UUID, payload: PetUpdate) -> Pet:
        pet = await self.get(pet_id)
        changes = payload.changes()
        for field, value in changes.items():
            setattr(pet, field, value)
        await self._repository.flush()
        log.info("pet.updated", pet_id=str(pet.id), fields=sorted(changes))
        return pet

    async def delete(self, pet_id: uuid.UUID) -> None:
        pet = await self.get(pet_id)
        await self._repository.delete(pet)
        log.info("pet.deleted", pet_id=str(pet_id))

    async def reserve(self, pet_id: uuid.UUID, *, owner_id: uuid.UUID) -> Pet:
        """A real business rule: reservation is only legal from AVAILABLE.

        Note what this is *not*: an HTTP concern. The route calls this and the error
        model turns :class:`PetAlreadyAdoptedError` into a 409 automatically.

        Note what it *is*: a read-decide-write sequence, which is a race unless the row
        is locked. Copy this shape -- ``_get_locked`` then check then write -- for any
        rule of the form "only allowed if the current state is X".
        """
        pet = await self._get_locked(pet_id)
        if pet.status is not AdoptionStatus.AVAILABLE:
            raise PetAlreadyAdoptedError(pet_id, pet.status)
        pet.status = AdoptionStatus.RESERVED
        pet.owner_id = owner_id
        await self._repository.flush()
        log.info("pet.reserved", pet_id=str(pet_id), owner_id=str(owner_id))
        return pet

    async def attach_photo(
        self,
        pet_id: uuid.UUID,
        *,
        source: AsyncReadable,
        content_type: str,
        max_bytes: int,
    ) -> Pet:
        """Reference implementation of an upload: the service speaks keys, not providers.

        Order matters here, and both steps were wrong in an earlier revision:

        1. **The pet is loaded first.** Writing the object before checking that the
           owner row exists leaves an orphaned file behind on every 404.
        2. **The superseded object is not deleted here.** The request transaction has
           not committed yet -- deleting it now and then failing to commit would leave
           a live row pointing at a file that no longer exists. Unreferenced objects are
           reclaimed by a sweeper (see docs/architecture.md); losing a referenced one is
           unrecoverable.
        """
        if self._storage is None:  # pragma: no cover - wiring error, not a runtime path
            raise RuntimeError("PetService was constructed without a storage backend.")

        pet = await self.get(pet_id)
        key = build_storage_key("pets", content_type=content_type)
        stored = await self._storage.save(
            key, source, content_type=content_type, max_bytes=max_bytes
        )

        superseded_key = pet.photo_key
        pet.photo_key = stored.key
        await self._repository.flush()

        if superseded_key:
            log.info("pet.photo_superseded", pet_id=str(pet_id), storage_key=superseded_key)
        log.info("pet.photo_attached", pet_id=str(pet_id), size_bytes=stored.size_bytes)
        return pet

    @staticmethod
    def sort_params(raw: str | None) -> SortParams:
        from app.modules.pets.repository import DEFAULT_SORT, SORTABLE_FIELDS

        return SortParams.parse(raw, allowed=SORTABLE_FIELDS, default=DEFAULT_SORT)
