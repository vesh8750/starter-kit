"""Outbound HTTP behaviour.

Retry logic is easy to write and easy to get subtly wrong, and its failure modes
(duplicated side effects, retry storms, hung requests) only appear under load. These
tests pin the rules down with a mock transport rather than a live server.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.context import REQUEST_ID_HEADER, bind_request_id_context
from app.core.errors import ServiceUnavailableError, UpstreamError
from app.integrations.http import ServiceClient


def build_client(handler, *, max_retries: int = 2) -> ServiceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://upstream")
    client = ServiceClient(http, max_retries=max_retries)
    client.service_name = "upstream"
    return client


async def test_transient_failures_are_retried_for_idempotent_methods():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client = build_client(handler)
    assert await client.get_json("/thing") == {"ok": True}
    assert attempts == 3


async def test_non_idempotent_methods_are_never_retried():
    """Retrying a POST that the server already processed duplicates the side effect."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    client = build_client(handler)
    with pytest.raises(UpstreamError):
        await client.request("POST", "/thing")
    assert attempts == 1


async def test_retries_are_bounded():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(502)

    client = build_client(handler, max_retries=2)
    with pytest.raises(UpstreamError):
        await client.request("GET", "/thing")
    assert attempts == 3  # the initial call plus two retries, never unbounded


async def test_connection_failures_become_service_unavailable_not_a_500():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = build_client(handler)
    with pytest.raises(ServiceUnavailableError):
        await client.request("GET", "/thing")


async def test_unexpected_status_does_not_leak_the_upstream_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="internal upstream stack trace")

    client = build_client(handler)
    with pytest.raises(UpstreamError) as exc_info:
        await client.request("GET", "/thing")
    assert "stack trace" not in exc_info.value.detail
    assert exc_info.value.extra["status_code"] == 418


async def test_malformed_json_is_an_upstream_error_not_a_parse_crash():
    client = build_client(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(UpstreamError):
        await client.get_json("/thing")


async def test_the_correlation_id_is_propagated_to_the_upstream():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={})

    client = build_client(handler)
    with bind_request_id_context("trace-123"):
        await client.get_json("/thing")
    assert seen[REQUEST_ID_HEADER.lower()] == "trace-123"


def test_clients_always_have_an_explicit_timeout():
    from app.integrations.http import build_async_client

    client = build_async_client(Settings(_env_file=None), base_url="http://upstream")
    assert client.timeout.read is not None
    assert client.timeout.connect is not None
