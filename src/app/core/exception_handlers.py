"""Translate exceptions into RFC 9457 problem responses.

This is the only place in the codebase that turns an exception into an HTTP response.
Four handlers cover everything:

* :class:`AppError`            -- our own, fully described errors.
* ``RequestValidationError``   -- FastAPI/Pydantic input validation, flattened into
                                  a stable ``errors`` list so clients can map field paths.
* ``HTTPException``            -- raised by Starlette internals and third-party code.
* ``Exception``                -- the safety net: logged with a traceback, reported to
                                  the client as a bare 500 with the request id, never
                                  leaking internals.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.context import REQUEST_ID_HEADER, get_request_id
from app.core.errors import AppError, InputValidationError, InternalError
from app.core.logging import get_logger
from app.core.responses import ProblemJSONResponse

log = get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


def _render(request: Request, error: AppError) -> Response:
    problem = error.to_problem(instance=request.url.path)
    request_id = get_request_id()
    if request_id:
        problem["request_id"] = request_id
    headers = dict(error.headers)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
    return ProblemJSONResponse(problem, status_code=error.status_code, headers=headers)


async def handle_app_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AppError)  # noqa: S101 - handler is registered for this type
    # Client mistakes are not operational incidents; only server faults are warnings.
    event = "request.failed" if exc.status_code >= 500 else "request.rejected"
    log.warning(
        event,
        code=exc.code,
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
        exc_info=exc.status_code >= 500,
    )
    return _render(request, exc)


async def handle_request_validation_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    violations: list[dict[str, Any]] = [
        {
            "location": ".".join(str(part) for part in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    log.info("request.invalid", path=request.url.path, violations=violations)
    return _render(
        request,
        InputValidationError(
            "The request payload failed validation.",
            extra={"errors": violations},
        ),
    )


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    error = AppError(detail=str(exc.detail), headers=dict(exc.headers or {}))
    error.status_code = exc.status_code
    error.code = _HTTP_CODES.get(exc.status_code, "http_error")
    error.title = _HTTP_TITLES.get(exc.status_code, "HTTP Error")
    if exc.status_code >= 500:
        log.error("request.failed", status_code=exc.status_code, path=request.url.path)
    return _render(request, error)


async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
    log.exception(
        "request.unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
    )
    return _render(request, InternalError())


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

_HTTP_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
