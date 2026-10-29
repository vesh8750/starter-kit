"""API contract for pets.

Separate schemas per direction and per operation, rather than one model reused
everywhere. It costs a few extra lines and buys the ability to evolve the database and
the API independently, plus the guarantee that a client cannot set a field simply
because the column exists (mass-assignment).

``PetCreate`` / ``PetUpdate`` differ meaningfully: update is a PATCH, so every field is
optional and "not supplied" must be distinguishable from "set to null" -- that is what
``model_fields_set`` gives us in :meth:`PetUpdate.changes`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.pets.models import AdoptionStatus, Pet, Species
from app.storage.base import FileStorage

Name = Annotated[str, Field(min_length=1, max_length=120)]
Weight = Annotated[Decimal, Field(gt=0, le=Decimal("999.99"), decimal_places=2)]


class PetBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Name
    species: Species
    breed: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    weight_kg: Weight | None = None
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("date_of_birth")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > datetime.now(UTC).date():
            raise ValueError("date_of_birth cannot be in the future")
        return value


class PetCreate(PetBase):
    status: AdoptionStatus = AdoptionStatus.AVAILABLE


class PetUpdate(BaseModel):
    """PATCH body. Unset fields are left untouched; explicit ``null`` clears a field."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Name | None = None
    species: Species | None = None
    breed: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    weight_kg: Weight | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: AdoptionStatus | None = None

    @model_validator(mode="after")
    def _reject_empty_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied")
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(exclude_unset=True)


class PetRead(BaseModel):
    """Response shape, built straight from the ORM model.

    Note what is *absent*: ``photo_key`` and ``owner_id``. A response model is an
    allowlist, so internal columns cannot leak by being added to the table later.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    species: Species
    breed: str | None
    date_of_birth: date | None
    weight_kg: Decimal | None
    status: AdoptionStatus
    description: str | None
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, pet: Pet, *, storage: FileStorage | None = None) -> PetRead:
        """Render a model for the API, resolving the storage key to a URL.

        URL construction lives here rather than in the service: which URL a key maps to
        is a presentation concern that depends on the storage backend, and keeping it
        out of the service is what lets the service stay testable without any storage.
        """
        read = cls.model_validate(pet)
        if storage is not None and pet.photo_key:
            return read.model_copy(update={"photo_url": storage.url_for(pet.photo_key)})
        return read


class PetFilters(BaseModel):
    """Query-string filters, validated like any other input."""

    model_config = ConfigDict(extra="forbid")

    species: Species | None = None
    status: AdoptionStatus | None = None
    search: str | None = Field(default=None, min_length=1, max_length=120)
