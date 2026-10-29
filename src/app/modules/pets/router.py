"""HTTP surface for pets.

Routes stay thin on purpose: parse and validate input, call the service, choose the
status code. No business rules, no query building, no error-to-response mapping -- those
belong to the service, the repository and the exception handlers respectively.

Note that responses are declared with ``response_model``/return annotations so the
OpenAPI schema (and therefore generated clients) stay accurate for free.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import DbSession, Pagination, SettingsDep, StorageDep, require_scopes
from app.core.errors import InputValidationError
from app.core.pagination import Page
from app.modules.pets.repository import SORTABLE_FIELDS, PetRepository
from app.modules.pets.schemas import PetCreate, PetFilters, PetRead, PetUpdate
from app.modules.pets.service import PetService

router = APIRouter(prefix="/pets", tags=["pets"])

ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def get_pet_service(session: DbSession, storage: StorageDep) -> PetService:
    """Single wiring point for the feature; tests override this one dependency."""
    return PetService(PetRepository(session), storage=storage)


PetServiceDep = Annotated[PetService, Depends(get_pet_service)]
FiltersDep = Annotated[PetFilters, Depends()]


@router.get("", summary="List pets", response_model=Page[PetRead])
async def list_pets(
    service: PetServiceDep,
    storage: StorageDep,
    page: Pagination,
    filters: FiltersDep,
    sort: Annotated[
        str | None,
        Query(
            description="Comma-separated fields, '-' prefix for descending. "
            f"Allowed: {', '.join(SORTABLE_FIELDS)}."
        ),
    ] = None,
) -> Page[PetRead]:
    pets, total = await service.list(filters=filters, page=page, sort=service.sort_params(sort))
    items = [PetRead.from_model(pet, storage=storage) for pet in pets]
    return Page[PetRead].build(items, total=total, params=page)


@router.get("/{pet_id}", summary="Get a pet", response_model=PetRead)
async def get_pet(pet_id: uuid.UUID, service: PetServiceDep, storage: StorageDep) -> PetRead:
    pet = await service.get(pet_id)
    return PetRead.from_model(pet, storage=storage)


@router.post(
    "", summary="Create a pet", status_code=status.HTTP_201_CREATED, response_model=PetRead
)
async def create_pet(payload: PetCreate, service: PetServiceDep, storage: StorageDep) -> PetRead:
    pet = await service.create(payload)
    return PetRead.from_model(pet, storage=storage)


@router.patch("/{pet_id}", summary="Update a pet", response_model=PetRead)
async def update_pet(
    pet_id: uuid.UUID, payload: PetUpdate, service: PetServiceDep, storage: StorageDep
) -> PetRead:
    pet = await service.update(pet_id, payload)
    return PetRead.from_model(pet, storage=storage)


@router.delete(
    "/{pet_id}",
    summary="Delete a pet",
    status_code=status.HTTP_204_NO_CONTENT,
    # Reference for protecting a route: authentication (401 without a token) and
    # authorisation (403 without the scope) are both handled by this one dependency.
    dependencies=[require_scopes("pets:admin")],
)
async def delete_pet(pet_id: uuid.UUID, service: PetServiceDep) -> None:
    await service.delete(pet_id)


@router.post("/{pet_id}/reservation", summary="Reserve a pet", response_model=PetRead)
async def reserve_pet(
    pet_id: uuid.UUID, owner_id: uuid.UUID, service: PetServiceDep, storage: StorageDep
) -> PetRead:
    pet = await service.reserve(pet_id, owner_id=owner_id)
    return PetRead.from_model(pet, storage=storage)


@router.put("/{pet_id}/photo", summary="Upload a pet photo", response_model=PetRead)
async def upload_pet_photo(
    pet_id: uuid.UUID,
    service: PetServiceDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP image")],
) -> PetRead:
    """Reference implementation of an upload.

    The declared content type is checked against an allowlist, and the stored object's
    name and extension are derived from that validated type -- never from the client's
    filename, which would otherwise let `photo.html` be written and later served.

    Note the layering: the request body size is capped by ``MaxBodySizeMiddleware``
    before anything is buffered; ``max_bytes`` here is the second, per-endpoint limit
    enforced while the object is written.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise InputValidationError(
            "Unsupported image type.",
            extra={"allowed_content_types": sorted(ALLOWED_IMAGE_TYPES)},
        )
    pet = await service.attach_photo(
        pet_id,
        source=file,
        content_type=file.content_type,
        max_bytes=settings.storage_max_upload_bytes,
    )
    return PetRead.from_model(pet, storage=storage)
