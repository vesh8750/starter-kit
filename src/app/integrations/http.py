"""Shared HTTP client foundation.

Three things every outbound call needs, and which are easy to forget one at a time:

* **Connection reuse.** One ``AsyncClient`` per service, created at startup and closed at
  shutdown. Creating a client per request throws away the connection pool and TLS
  session cache, and leaks sockets under load.
* **Timeouts, always.** ``httpx`` defaults to 5s; we set an explicit budget from
  configuration. A call with no timeout is an outage waiting to happen.
* **Error translation.** Upstream failures surface as :class:`UpstreamError` /
  :class:`ServiceUnavailableError`, never as a raw ``httpx`` exception escaping into a
  500 with a stack trace mentioning a vendor's hostname.

Retries use tenacity and apply only to idempotent methods and transient failures --
retrying a POST that timed out after the server processed it duplicates the side effect.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Self

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.core.context import REQUEST_ID_HEADER, get_request_id
from app.core.errors import ServiceUnavailableError, UpstreamError
from app.core.logging import get_logger

log = get_logger(__name__)

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class RetryableStatusError(Exception):
    """Internal signal: an upstream returned a status worth retrying."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Retryable status {response.status_code}")


def build_async_client(
    settings: Settings,
    *,
    base_url: str = "",
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(
            settings.http_timeout_seconds, connect=min(5.0, settings.http_timeout_seconds)
        ),
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_connections // 5 or 1,
        ),
        headers={
            "User-Agent": f"{settings.project_name}/{settings.environment}",
            **(headers or {}),
        },
        follow_redirects=False,  # opt in per call; silent redirects hide auth leaks
    )


class ServiceClient:
    """Base class for a single upstream service.

    Subclass it, expose *domain* methods (``async def fetch_breed(...) -> Breed``) and
    keep HTTP details inside. Callers should never see a ``Response``.
    """

    service_name: str = "upstream"

    def __init__(self, client: httpx.AsyncClient, *, max_retries: int = 2) -> None:
        self._client = client
        self._max_retries = max_retries

    @classmethod
    @asynccontextmanager
    async def create(cls, settings: Settings, base_url: str) -> AsyncIterator[Self]:
        """Convenience for scripts and tests; long-lived apps build one in the lifespan."""
        async with build_async_client(settings, base_url=base_url) as client:
            yield cls(client, max_retries=settings.http_max_retries)

    async def request(
        self,
        method: str,
        url: str,
        *,
        expected_status: set[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers: dict[str, str] = dict(kwargs.pop("headers", {}) or {})
        # Propagate the correlation id so a trace survives the service boundary.
        if (request_id := get_request_id()) is not None:
            headers.setdefault(REQUEST_ID_HEADER, request_id)

        retries = self._max_retries if method.upper() in IDEMPOTENT_METHODS else 0
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(retries + 1),
                wait=wait_exponential_jitter(initial=0.1, max=2.0),
                retry=retry_if_exception_type((httpx.TransportError, RetryableStatusError)),
                reraise=True,
            ):
                with attempt:
                    response = await self._send(method, url, headers=headers, **kwargs)
        except RetryError as exc:  # pragma: no cover - reraise=True makes this rare
            raise ServiceUnavailableError(f"{self.service_name} is unavailable.") from exc
        except httpx.TransportError as exc:
            log.warning("http.transport_error", service=self.service_name, url=url, error=str(exc))
            raise ServiceUnavailableError(f"{self.service_name} is unreachable.") from exc
        except RetryableStatusError as exc:
            raise UpstreamError(
                f"{self.service_name} returned {exc.response.status_code}.",
                extra={"service": self.service_name},
            ) from exc

        allowed = expected_status or set(range(200, 300))
        if response.status_code not in allowed:
            log.warning(
                "http.unexpected_status",
                service=self.service_name,
                url=url,
                status_code=response.status_code,
            )
            raise UpstreamError(
                f"{self.service_name} returned an unexpected status.",
                extra={"service": self.service_name, "status_code": response.status_code},
            )
        return response

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, url, **kwargs)
        if response.status_code in RETRYABLE_STATUS:
            raise RetryableStatusError(response)
        return response

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.request("GET", url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"{self.service_name} returned a malformed response.") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
