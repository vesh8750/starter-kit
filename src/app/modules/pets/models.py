"""Persistence model for pets.

Models describe the *database*, not the API. Constraints that protect data integrity are
declared here (and therefore enforced by Postgres for every writer, including migrations
and manual SQL), while presentation concerns live in ``schemas.py``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column


class Species(enum.StrEnum):
    DOG = "dog"
    CAT = "cat"
    BIRD = "bird"
    RABBIT = "rabbit"
    OTHER = "other"


class AdoptionStatus(enum.StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ADOPTED = "adopted"


class Pet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pets"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[Species] = mapped_column(
        enum_column(Species, "species"),
        nullable=False,
        index=True,
    )
    breed: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[AdoptionStatus] = mapped_column(
        enum_column(AdoptionStatus, "adoption_status"),
        nullable=False,
        default=AdoptionStatus.AVAILABLE,
        server_default=AdoptionStatus.AVAILABLE.value,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Storage *key*, not a path or URL. Resolved to a URL by the storage backend at
    # serialisation time, so moving from local disk to object storage changes no rows.
    photo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("weight_kg IS NULL OR weight_kg > 0", name="weight_positive"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # Supports the default listing (status filter + newest first) with one index.
        Index("ix_pets_status_created_at", "status", "created_at"),
    )
