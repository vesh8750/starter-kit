"""Service-level tests with a fake repository.

Demonstrates the payoff of keeping business rules out of routes and SQL: the rule under
test needs no database, no HTTP and no fixtures beyond a dozen lines of fake.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.pets.exceptions import PetAlreadyAdoptedError, PetNotFoundError
from app.modules.pets.models import AdoptionStatus, Pet
from app.modules.pets.schemas import PetUpdate
from app.modules.pets.service import PetService
from tests.factories import make_pet


class FakePetRepository:
    def __init__(self, pets: dict[uuid.UUID, Pet] | None = None) -> None:
        self.pets = pets or {}
        self.flushed = 0
        self.locked: list[uuid.UUID] = []

    async def get(self, pet_id: uuid.UUID) -> Pet | None:
        return self.pets.get(pet_id)

    async def get_for_update(self, pet_id: uuid.UUID) -> Pet | None:
        self.locked.append(pet_id)
        return self.pets.get(pet_id)

    def add(self, pet: Pet) -> Pet:
        self.pets[pet.id] = pet
        return pet

    async def delete(self, pet: Pet) -> None:
        self.pets.pop(pet.id, None)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.fixture
def pet() -> Pet:
    stored = make_pet()
    stored.id = uuid.uuid4()
    return stored


@pytest.fixture
def service(pet: Pet) -> PetService:
    return PetService(FakePetRepository({pet.id: pet}))  # type: ignore[arg-type]


async def test_get_missing_pet_raises_domain_error(service: PetService):
    with pytest.raises(PetNotFoundError) as exc_info:
        await service.get(uuid.uuid4())
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "pet_not_found"


async def test_reserve_marks_the_pet_and_records_the_owner(service: PetService, pet: Pet):
    owner_id = uuid.uuid4()
    reserved = await service.reserve(pet.id, owner_id=owner_id)
    assert reserved.status is AdoptionStatus.RESERVED
    assert reserved.owner_id == owner_id


async def test_reserving_twice_is_a_conflict(service: PetService, pet: Pet):
    await service.reserve(pet.id, owner_id=uuid.uuid4())
    with pytest.raises(PetAlreadyAdoptedError) as exc_info:
        await service.reserve(pet.id, owner_id=uuid.uuid4())
    assert exc_info.value.status_code == 409
    assert exc_info.value.extra["current_status"] == "reserved"


async def test_reserve_locks_the_row_before_deciding(service: PetService, pet: Pet):
    """Read-decide-write without a row lock is a lost update: two concurrent callers
    both see 'available' and both win."""
    await service.reserve(pet.id, owner_id=uuid.uuid4())
    repository = service._repository  # asserting the locking contract
    assert repository.locked == [pet.id]  # type: ignore[attr-defined]


async def test_patch_only_touches_supplied_fields(service: PetService, pet: Pet):
    original_name = pet.name
    updated = await service.update(pet.id, PetUpdate(description="calm"))
    assert updated.description == "calm"
    assert updated.name == original_name


async def test_patch_can_explicitly_clear_a_field(service: PetService, pet: Pet):
    updated = await service.update(pet.id, PetUpdate(breed=None))
    assert updated.breed is None
