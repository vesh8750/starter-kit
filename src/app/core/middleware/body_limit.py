"""Request body size limit.

Without this, an attacker can POST an arbitrarily large body and Starlette will buffer
it -- spooling multipart uploads to disk -- *before* any endpoint code runs. The
per-endpoint ``max_bytes`` passed to the storage layer is therefore a second line of
defence, not the first: by the time it applies, the bytes have already been accepted.

Two checks, because either alone is insufficient:

* ``Content-Length`` is rejected up front, so an honest large upload costs nothing.
* The streamed body is counted as it arrives, so a chunked request that omits or
  understates ``Content-Length`` is cut off mid-flight.

A reverse proxy should enforce a limit as well (``client_max_body_size`` in nginx). This
exists so the application is not defenceless when deployed without one.

Known limitation: a request with no ``Content-Length`` (chunked transfer encoding) is
cut off as soon as the limit is passed, but the framework's body parser turns the
truncated stream into a 400 before this middleware can answer with 413. The protection
that matters -- bounded memory and disk -- holds in both cases; only the status code is
less precise for chunked uploads.

Implementation note: this middleware renders its own response instead of raising. Pure
ASGI middleware sits *outside* Starlette's ``ExceptionMiddleware``, so an exception
raised here would never reach the application's exception handlers -- it would surface
as a bare 500. Anything that rejects a request from middleware must send the response
itself, and must keep that response in the same problem+json shape as the rest of the API.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import REQUEST_ID_HEADER, get_request_id
from app.core.errors import PayloadTooLargeError
from app.core.logging import get_logger
from app.core.responses import ProblemJSONResponse

log = get_logger(__name__)

_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})


class _BodyTooLargeError(Exception):
    """Internal signal raised from the receive channel once the limit is exceeded."""


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            log.warning("request.body_too_large", declared_bytes=declared, limit=self.max_bytes)
            await self._reject(scope, send)
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    log.warning(
                        "request.body_too_large", received_bytes=received, limit=self.max_bytes
                    )
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLargeError:
            # Only safe to answer if nothing has been sent yet; otherwise the only
            # honest option is to drop the connection.
            if not response_started:
                await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        error = PayloadTooLargeError(
            "The request body exceeds the permitted size.",
            extra={"max_bytes": self.max_bytes},
        )
        problem = error.to_problem(instance=scope.get("path", ""))
        headers = {"Connection": "close"}
        if (request_id := get_request_id()) is not None:
            problem["request_id"] = request_id
            headers[REQUEST_ID_HEADER] = request_id
        response = ProblemJSONResponse(problem, status_code=error.status_code, headers=headers)
        await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
