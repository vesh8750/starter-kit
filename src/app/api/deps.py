"""Shared API dependencies.

Anything a route needs and that more than one feature uses lives here as a ready-made
``Annotated`` alias, so signatures stay short and the wiring is written once:

    async def handler(session: DbSession, page: Pagination, user: CurrentPrincipal) -> ...
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.cache.factory import CacheDep
from app.core.config import Settings, get_settings
from app.core.context import Principal, set_principal
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.logging import bind_log_context
from app.core.pagination import Pagination
from app.core.security import principal_from_token
from app.db.session import DbSession
from app.storage.factory import StorageDep

SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing header produces our problem+json 401 rather than
# Starlette's plain JSON body.
_bearer = HTTPBearer(auto_error=False, description="JWT access token")
BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def get_optional_principal(
    credentials: BearerToken, settings: SettingsDep
) -> Principal | None:
    """Resolve the caller when a token is present; ``None`` for anonymous requests."""
    if credentials is None:
        return None
    principal = principal_from_token(settings, credentials.credentials)
    set_principal(principal)
    # Every subsequent log line in this request names the caller. Only the subject and
    # scopes -- never the token, and never any other claim, which may carry PII.
    bind_log_context(principal=principal.subject, scopes=sorted(principal.scopes))
    return principal


async def get_current_principal(
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> Principal:
    if principal is None:
        raise AuthenticationError()
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]


def require_scopes(*required: str) -> Any:
    """Route-level authorisation:

        @router.post("/", dependencies=[require_scopes("pets:write")])

    Scopes are strings carried in the token, so this works unchanged whether they end up
    coming from a user's roles, an API key or a machine-to-machine client.
    """

    async def _check(principal: CurrentPrincipal) -> None:
        missing = [scope for scope in required if not principal.has_scope(scope)]
        if missing:
            raise PermissionDeniedError(
                "Missing required permissions.",
                extra={"required_scopes": list(required), "missing_scopes": missing},
            )

    return Depends(_check)


def get_request_state(request: Request) -> Request:
    """Escape hatch for the rare route that genuinely needs the raw request."""
    return request


__all__ = [
    "BearerToken",
    "CacheDep",
    "CurrentPrincipal",
    "DbSession",
    "OptionalPrincipal",
    "Pagination",
    "SettingsDep",
    "StorageDep",
    "get_current_principal",
    "get_optional_principal",
    "get_request_state",
    "require_scopes",
]
