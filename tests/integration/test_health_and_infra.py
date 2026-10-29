from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_liveness_never_depends_on_the_database(client: AsyncClient):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_reports_dependency_checks(client: AsyncClient):
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["database"]["status"] == "ok"


async def test_security_headers_are_applied(client: AsyncClient):
    response = await client.get("/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_metrics_endpoint_exposes_request_counters(client: AsyncClient):
    await client.get("/api/v1/pets?limit=1")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    # Route templates, not raw paths -- otherwise every id becomes a new time series.
    assert "/api/v1/pets" in response.text


async def test_unknown_route_returns_problem_json(client: AsyncClient):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


async def test_openapi_documents_the_error_schema(client: AsyncClient):
    schema = (await client.get("/openapi.json")).json()
    assert "Problem" in schema["components"]["schemas"]
    assert "bearerAuth" in schema["components"]["securitySchemes"]
