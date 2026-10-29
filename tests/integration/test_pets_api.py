"""End-to-end tests through the real ASGI stack.

These go through middleware, dependency injection, the database and the exception
handlers -- i.e. they test what a client will actually receive.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.context import REQUEST_ID_HEADER
from tests.factories import pet_payload
from tests.integration.test_security_boundaries import auth_header

pytestmark = pytest.mark.integration

PETS = "/api/v1/pets"


async def create_pet(client: AsyncClient, **overrides: object) -> dict:
    response = await client.post(PETS, json=pet_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_returns_201_with_generated_fields(client: AsyncClient):
    pet = await create_pet(client, name="Rex")
    assert uuid.UUID(pet["id"])
    assert pet["status"] == "available"
    assert pet["created_at"]


async def test_every_response_carries_a_correlation_id(client: AsyncClient):
    response = await client.get(f"{PETS}?limit=1")
    assert response.headers[REQUEST_ID_HEADER]


async def test_inbound_correlation_id_is_preserved(client: AsyncClient):
    response = await client.get(f"{PETS}?limit=1", headers={REQUEST_ID_HEADER: "trace-abc"})
    assert response.headers[REQUEST_ID_HEADER] == "trace-abc"


async def test_get_missing_pet_returns_problem_json(client: AsyncClient):
    response = await client.get(f"{PETS}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "pet_not_found"
    assert body["request_id"]


async def test_validation_errors_list_the_offending_fields(client: AsyncClient):
    response = await client.post(PETS, json={"name": "", "species": "dragon"})
    assert response.status_code == 422
    locations = {error["location"] for error in response.json()["errors"]}
    assert any("species" in location for location in locations)


async def test_unknown_fields_are_rejected(client: AsyncClient):
    response = await client.post(PETS, json=pet_payload(is_admin=True))
    assert response.status_code == 422


async def test_listing_filters_sorts_and_paginates(client: AsyncClient):
    await create_pet(client, name="Alpha", species="dog")
    await create_pet(client, name="Beta", species="cat")
    await create_pet(client, name="Gamma", species="dog")

    response = await client.get(f"{PETS}?species=dog&sort=name&limit=1")
    body = response.json()
    assert response.status_code == 200
    assert [item["name"] for item in body["items"]] == ["Alpha"]
    assert body["meta"]["total"] == 2
    assert body["meta"]["has_more"] is True

    page_two = await client.get(f"{PETS}?species=dog&sort=name&limit=1&offset=1")
    assert [item["name"] for item in page_two.json()["items"]] == ["Gamma"]
    assert page_two.json()["meta"]["has_more"] is False


async def test_search_matches_name_and_breed(client: AsyncClient):
    await create_pet(client, name="Zephyr", breed="Poodle")
    response = await client.get(f"{PETS}?search=poodl")
    assert [item["name"] for item in response.json()["items"]] == ["Zephyr"]


async def test_invalid_sort_field_is_rejected(client: AsyncClient):
    response = await client.get(f"{PETS}?sort=secret_column")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_pagination_limit_is_capped(client: AsyncClient):
    assert (await client.get(f"{PETS}?limit=10000")).status_code == 422


async def test_patch_updates_only_supplied_fields(client: AsyncClient):
    pet = await create_pet(client, name="Rex", breed="Labrador")
    response = await client.patch(f"{PETS}/{pet['id']}", json={"description": "good boy"})
    assert response.status_code == 200
    assert response.json()["description"] == "good boy"
    assert response.json()["breed"] == "Labrador"


async def test_empty_patch_is_rejected(client: AsyncClient):
    pet = await create_pet(client)
    assert (await client.patch(f"{PETS}/{pet['id']}", json={})).status_code == 422


async def test_reservation_conflict_returns_409(client: AsyncClient):
    pet = await create_pet(client)
    owner = uuid.uuid4()
    first = await client.post(f"{PETS}/{pet['id']}/reservation?owner_id={owner}")
    assert first.status_code == 200
    assert first.json()["status"] == "reserved"

    second = await client.post(f"{PETS}/{pet['id']}/reservation?owner_id={owner}")
    assert second.status_code == 409
    assert second.json()["code"] == "pet_already_adopted"


async def test_delete_then_get_returns_404(client: AsyncClient, settings):
    pet = await create_pet(client)
    # DELETE is scope-protected; see tests/integration/test_security_boundaries.py.
    headers = auth_header(settings, "pets:admin")
    assert (await client.delete(f"{PETS}/{pet['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"{PETS}/{pet['id']}")).status_code == 404


async def test_photo_upload_rejects_non_images(client: AsyncClient):
    pet = await create_pet(client)
    response = await client.put(
        f"{PETS}/{pet['id']}/photo",
        files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")},
    )
    assert response.status_code == 422


async def test_pagination_is_stable_when_the_sort_key_has_duplicates(client: AsyncClient):
    """Without a unique tiebreaker in ORDER BY, Postgres may order equal rows
    differently per query, so paging silently repeats some rows and skips others."""
    for _ in range(6):
        await create_pet(client, name="SameName")

    collected: list[str] = []
    for offset in range(0, 6, 2):
        page = await client.get(f"{PETS}?search=SameName&sort=name&limit=2&offset={offset}")
        collected.extend(item["id"] for item in page.json()["items"])

    assert len(collected) == 6
    assert len(set(collected)) == 6, "paging returned the same row on more than one page"


async def test_upload_extension_comes_from_the_content_type(client: AsyncClient):
    """A client that lies about its filename must not control the stored extension."""
    pet = await create_pet(client)
    response = await client.put(
        f"{PETS}/{pet['id']}/photo",
        files={"file": ("payload.html", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
    )
    assert response.status_code == 200, response.text
    photo_url = response.json()["photo_url"]
    assert photo_url.endswith(".png")
    assert "html" not in photo_url


async def test_upload_to_a_missing_pet_does_not_store_an_orphan(client: AsyncClient, settings):
    """The owning row is verified before anything is written to storage."""
    before = sorted(settings.storage_local_path.rglob("*"))
    response = await client.put(
        f"{PETS}/{uuid.uuid4()}/photo",
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
    )
    assert response.status_code == 404
    assert sorted(settings.storage_local_path.rglob("*")) == before


async def test_photo_upload_stores_the_file_and_exposes_a_url(client: AsyncClient):
    pet = await create_pet(client)
    response = await client.put(
        f"{PETS}/{pet['id']}/photo",
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["photo_url"].endswith(".png")
