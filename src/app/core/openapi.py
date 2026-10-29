"""OpenAPI customisation.

Two things worth doing centrally: declaring the bearer scheme once so the docs have a
working "Authorize" button, and documenting the shared error response so every endpoint
advertises the problem+json shape without repeating it in each decorator.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import Settings

PROBLEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "RFC 9457 problem details.",
    "properties": {
        "type": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "code": {"type": "string", "description": "Stable machine-readable error code."},
        "instance": {"type": "string"},
        "request_id": {"type": "string"},
    },
    "required": ["type", "title", "status", "detail", "code"],
}

DESCRIPTION = """
Errors are returned as `application/problem+json` (RFC 9457). Branch on the stable
`code` field rather than parsing `detail`, and quote `request_id` when reporting issues.

List endpoints accept `limit`, `offset` and `sort` and return `{ items, meta }`.
"""


def configure_openapi(app: FastAPI, settings: Settings) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=f"{settings.project_name} API",
            version=app.version,
            description=DESCRIPTION,
            routes=app.routes,
            servers=[{"url": settings.root_path or "/"}],
        )
        components = schema.setdefault("components", {})
        components.setdefault("schemas", {})["Problem"] = PROBLEM_SCHEMA
        components.setdefault("securitySchemes", {})["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        _document_error_responses(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def _document_error_responses(schema: dict[str, Any]) -> None:
    problem_ref = {
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        }
    }
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("422", {"description": "Validation error", **problem_ref})
            responses.setdefault("500", {"description": "Internal error", **problem_ref})
