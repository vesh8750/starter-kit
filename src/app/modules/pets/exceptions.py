"""Feature-specific errors.

Subclassing the shared error types keeps the HTTP mapping automatic while giving the
failure a precise ``code`` that clients can branch on and that shows up in logs and
dashboards.
"""

from __future__ import annotations

import uuid

from app.core.errors import ConflictError, NotFoundError
from app.modules.pets.models import AdoptionStatus


class PetNotFoundError(NotFoundError):
    code = "pet_not_found"

    def __init__(self, pet_id: uuid.UUID | str) -> None:
        super().__init__(f"Pet '{pet_id}' was not found.", extra={"pet_id": str(pet_id)})


class PetAlreadyAdoptedError(ConflictError):
    code = "pet_already_adopted"

    def __init__(self, pet_id: uuid.UUID, status: AdoptionStatus) -> None:
        super().__init__(
            "This pet is no longer available for adoption.",
            extra={"pet_id": str(pet_id), "current_status": status.value},
        )
