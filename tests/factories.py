"""Object builders for tests.

Plain functions with sensible defaults beat a factory library here: no extra dependency,
no magic, and a test only states the fields it actually cares about.
"""

from __future__ import annotations

from typing import Any

from app.modules.pets.models import AdoptionStatus, Pet, Species


def make_pet(**overrides: Any) -> Pet:
    data: dict[str, Any] = {
        "name": "Rex",
        "species": Species.DOG,
        "breed": "Labrador",
        "status": AdoptionStatus.AVAILABLE,
    }
    data.update(overrides)
    return Pet(**data)


def pet_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Rex", "species": "dog", "breed": "Labrador"}
    payload.update(overrides)
    return payload
