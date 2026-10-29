from __future__ import annotations

import hashlib
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Minimal cache contract.

    Values are JSON-serialisable. Kept deliberately small -- every method added here has
    to be implemented by every backend, and the four below cover caching, invalidation
    and simple distributed locks/counters.
    """

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, *keys: str) -> None: ...

    async def clear_prefix(self, prefix: str) -> None: ...

    async def close(self) -> None: ...


def cache_key(namespace: str, *parts: object) -> str:
    """Build a stable, length-bounded key: ``pets:list:9f2a...``.

    Long or user-controlled fragments are hashed so a key can never blow past backend
    limits or leak raw input into a shared keyspace.
    """
    raw = ":".join(str(part) for part in parts)
    if len(raw) > 96:
        raw = hashlib.sha256(raw.encode()).hexdigest()
    return f"{namespace}:{raw}" if raw else namespace
