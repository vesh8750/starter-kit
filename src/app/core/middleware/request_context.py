"""Correlation id, log binding and access logging."""

from __future__ import annotations

import time
import uuid
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import (
    REQUEST_ID_HEADER,
    bind_request_id_context,
)
from app.core.logging import bind_log_context, clear_log_context, get_logger

log = get_logger("app.access")

_MAX_REQUEST_ID_LENGTH: Final = 128
_SILENT_PATHS: Final = frozenset({"/health/live", "/health/ready", "/metrics"})


class RequestContextMiddleware:
    """Assign a request id, expose it everywhere, and emit one access log line.

    The id is taken from the inbound ``X-Request-ID`` when present so that a trace
    started by a gateway or a calling service continues through this application, and is
    always echoed on the response so a client can quote it in a bug report.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        path: str = scope.get("path", "")
        method: str = scope.get("method", "")
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with bind_request_id_context(request_id):
            clear_log_context()
            bind_log_context(request_id=request_id, method=method, path=path)
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                scope.setdefault("state", {})["duration_ms"] = duration_ms
                if path not in _SILENT_PATHS:
                    log.info(
                        "http.request",
                        status_code=status_code,
                        duration_ms=duration_ms,
                        client=_client_host(scope),
                    )
                clear_log_context()


def _incoming_request_id(scope: Scope) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for raw_name, raw_value in headers:
        if raw_name == b"x-request-id":
            value: str = raw_value.decode("latin-1").strip()
            # Untrusted input: it ends up in logs, so bound the length and charset.
            if value and len(value) <= _MAX_REQUEST_ID_LENGTH and value.isprintable():
                return value
            return None
    return None


def _client_host(scope: Scope) -> str | None:
    client = scope.get("client")
    return str(client[0]) if client else None
