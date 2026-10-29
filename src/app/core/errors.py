"""The application's error model.

Every failure the API can produce is an :class:`AppError`. Business code raises these
(or a module-specific subclass) and never builds an HTTP response itself -- the
exception handlers in :mod:`app.core.exception_handlers` translate them into
RFC 9457 ``application/problem+json`` responses.

Why RFC 9457 instead of a bespoke ``{"success": false, ...}`` envelope: it is a real
standard, clients can rely on the ``type``/``status``/``detail`` triple, and arbitrary
extension members let a specific error carry structured data (e.g. field violations)
without inventing a new shape each time.
"""

from __future__ import annotations

from typing import Any

PROBLEM_BASE_URI = "https://errors.example.com"


class AppError(Exception):
    """Base class for expected, client-communicable failures.

    Subclasses set the class-level attributes; call sites supply ``detail`` (human
    readable, safe to show) and optional ``extra`` members.
    """

    status_code: int = 500
    code: str = "internal_error"
    title: str = "Internal Server Error"
    default_detail: str = "An unexpected error occurred."

    def __init__(
        self,
        detail: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        self.extra = extra or {}
        self.headers = headers or {}
        super().__init__(self.detail)

    @property
    def problem_type(self) -> str:
        return f"{PROBLEM_BASE_URI}/{self.code}"

    def to_problem(self, *, instance: str | None = None) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": self.problem_type,
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "code": self.code,
        }
        if instance:
            problem["instance"] = instance
        problem.update(self.extra)
        return problem


# -- 4xx ----------------------------------------------------------------------


class InputValidationError(AppError):
    """Request payload failed validation. Carries per-field violations.

    Deliberately *not* named ``ValidationError``: this codebase imports Pydantic in most
    modules, and two different exceptions with the same name is how ``except
    ValidationError`` ends up catching the wrong one.
    """

    status_code = 422
    code = "validation_error"
    title = "Validation Error"
    default_detail = "The request payload failed validation."


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    title = "Unauthorized"
    default_detail = "Authentication credentials were missing or invalid."

    def __init__(self, detail: str | None = None, **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)
        self.headers.setdefault("WWW-Authenticate", "Bearer")


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    title = "Forbidden"
    default_detail = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    title = "Not Found"
    default_detail = "The requested resource does not exist."

    @classmethod
    def for_resource(cls, resource: str, identifier: object) -> NotFoundError:
        return cls(
            f"{resource} '{identifier}' was not found.",
            extra={"resource": resource, "identifier": str(identifier)},
        )


class ConflictError(AppError):
    """State conflict: uniqueness violation, duplicate action, version mismatch."""

    status_code = 409
    code = "conflict"
    title = "Conflict"
    default_detail = "The request conflicts with the current state of the resource."


class UnprocessableError(AppError):
    """Syntactically valid but semantically rejected by a business rule."""

    status_code = 422
    code = "unprocessable"
    title = "Unprocessable Content"
    default_detail = "The request could not be processed."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too Many Requests"
    default_detail = "Rate limit exceeded."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    title = "Payload Too Large"
    default_detail = "The uploaded payload exceeds the permitted size."


# -- 5xx ----------------------------------------------------------------------


class InternalError(AppError):
    """Explicitly raised server fault. Detail is never taken from an exception string."""

    status_code = 500
    code = "internal_error"
    title = "Internal Server Error"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Service Unavailable"
    default_detail = "The service is temporarily unavailable."


class UpstreamError(AppError):
    """A required external dependency failed or misbehaved."""

    status_code = 502
    code = "upstream_error"
    title = "Bad Gateway"
    default_detail = "An upstream service failed to respond correctly."
