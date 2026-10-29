"""Ambient request context.

Correlation data (request id, authenticated principal) is needed by code that has no
business taking a ``Request`` parameter -- log processors, repositories, outbound HTTP
clients. Context variables keep it available without threading it through every call,
and they are asyncio-task-local so concurrent requests never observe each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Final

_REQUEST_ID: Final[ContextVar[str | None]] = ContextVar("request_id", default=None)
_PRINCIPAL: Final[ContextVar[Principal | None]] = ContextVar("principal", default=None)

REQUEST_ID_HEADER: Final = "X-Request-ID"


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Deliberately decoupled from any user table."""

    subject: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def set_request_id(request_id: str) -> Token[str | None]:
    return _REQUEST_ID.set(request_id)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def set_principal(principal: Principal | None) -> Token[Principal | None]:
    return _PRINCIPAL.set(principal)


def get_principal() -> Principal | None:
    return _PRINCIPAL.get()


def reset_principal(token: Token[Principal | None]) -> None:
    _PRINCIPAL.reset(token)


@contextmanager
def bind_request_id_context(request_id: str) -> Iterator[str]:
    """Scope a request id to a block, restoring the previous value on exit."""
    token = set_request_id(request_id)
    try:
        yield request_id
    finally:
        reset_request_id(token)


@contextmanager
def bind_principal_context(principal: Principal | None) -> Iterator[Principal | None]:
    token = set_principal(principal)
    try:
        yield principal
    finally:
        reset_principal(token)
