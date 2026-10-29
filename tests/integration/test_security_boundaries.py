"""Authentication, authorisation, and the request-size limit.

These cover the paths that are security-relevant and therefore must not regress
silently: they are cheap to break and expensive to discover in production.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.security import create_access_token
from tests.factories import pet_payload

pytestmark = pytest.mark.integration

PETS = "/api/v1/pets"


def auth_header(settings: Settings, *scopes: str) -> dict[str, str]:
    token = create_access_token(settings, subject=str(uuid.uuid4()), scopes=set(scopes))
    return {"Authorization": f"Bearer {token.access_token}"}


async def test_protected_route_rejects_anonymous_callers(client: AsyncClient):
    pet = (await client.post(PETS, json=pet_payload())).json()
    response = await client.delete(f"{PETS}/{pet['id']}")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_protected_route_rejects_a_token_without_the_scope(
    client: AsyncClient, settings: Settings
):
    pet = (await client.post(PETS, json=pet_payload())).json()
    response = await client.delete(
        f"{PETS}/{pet['id']}", headers=auth_header(settings, "pets:read")
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert response.json()["missing_scopes"] == ["pets:admin"]


async def test_protected_route_accepts_a_correctly_scoped_token(
    client: AsyncClient, settings: Settings
):
    pet = (await client.post(PETS, json=pet_payload())).json()
    response = await client.delete(
        f"{PETS}/{pet['id']}", headers=auth_header(settings, "pets:admin")
    )
    assert response.status_code == 204


async def test_a_garbage_token_is_rejected(client: AsyncClient):
    response = await client.delete(
        f"{PETS}/{uuid.uuid4()}", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_a_token_signed_with_another_key_is_rejected(client: AsyncClient):
    other = Settings(_env_file=None, secret_key="attacker-controlled-key-" + "x" * 32)
    response = await client.delete(
        f"{PETS}/{uuid.uuid4()}", headers=auth_header(other, "pets:admin")
    )
    assert response.status_code == 401


async def test_oversized_body_is_rejected_before_it_is_buffered(
    client: AsyncClient, settings: Settings
):
    oversized = b"x" * (settings.max_request_body_bytes + 1024)
    response = await client.post(
        PETS, content=oversized, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


async def test_error_responses_never_leak_internals(client: AsyncClient):
    """An unhandled server fault must expose a request id and nothing else."""
    response = await client.get(f"{PETS}/not-a-uuid")
    body = response.json()
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "sqlalchemy" not in response.text.lower()
    assert body["request_id"]
