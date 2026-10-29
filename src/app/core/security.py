"""Password hashing and JWT primitives.

Deliberately *not* an auth system: there is no user model, no login endpoint and no
session store, because those are product decisions. What is provided is the mechanical
half that every scheme needs and that is easy to get wrong -- a modern password hash and
signed, expiring tokens. Wiring them to a real user store is a feature, not foundation;
see docs/architecture.md ("Authentication") for the intended shape.

Argon2id (via pwdlib) is the current OWASP-recommended password hash. PyJWT is used for
tokens; switching to asymmetric RS256/EdDSA later is a settings change plus a key source.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import AuthenticationError

_password_hash: Final = PasswordHash.recommended()

TOKEN_TYPE_ACCESS: Final = "access"  # noqa: S105 - a claim value, not a secret


def hash_password(plain_password: str) -> str:
    return _password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verification. Returns False rather than raising on a malformed hash."""
    try:
        return _password_hash.verify(plain_password, hashed_password)
    except (UnknownHashError, ValueError, TypeError):
        return False


def verify_and_upgrade(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    """Verify, and return a re-hashed value when the stored hash uses stale parameters.

    Call this from a login flow and persist the new hash when the second item is not
    ``None`` -- that is how password hashes stay current as the cost parameters move.
    """
    try:
        valid, updated = _password_hash.verify_and_update(plain_password, hashed_password)
    except (UnknownHashError, ValueError, TypeError):
        return False, None
    return valid, updated


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    expires_at: datetime
    token_type: str = "Bearer"  # noqa: S105 - a scheme name, not a credential


def create_access_token(
    settings: Settings,
    *,
    subject: str,
    scopes: frozenset[str] | set[str] | None = None,
    extra_claims: dict[str, Any] | None = None,
    ttl: timedelta | None = None,
) -> TokenPair:
    now = datetime.now(UTC)
    expires_at = now + (ttl or timedelta(seconds=settings.access_token_ttl_seconds))
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
        "typ": TOKEN_TYPE_ACCESS,
        "scopes": sorted(scopes or ()),
        **(extra_claims or {}),
    }
    token = jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)
    return TokenPair(access_token=token, expires_at=expires_at)


def decode_token(settings: Settings, token: str) -> dict[str, Any]:
    """Verify signature and expiry. Raises :class:`AuthenticationError` on any problem."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("The access token is invalid.") from exc
    return claims


def principal_from_token(settings: Settings, token: str) -> Principal:
    claims = decode_token(settings, token)
    if claims.get("typ") != TOKEN_TYPE_ACCESS:
        raise AuthenticationError("Unexpected token type.")
    return Principal(subject=str(claims["sub"]), scopes=frozenset(claims.get("scopes", ())))
