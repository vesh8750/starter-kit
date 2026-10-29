from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import orjson


@dataclass(slots=True)
class _Entry:
    value: bytes
    expires_at: float | None


class InMemoryCache:
    """Process-local cache. Correct for one instance, and the right default for tests.

    Not shared between workers -- if the deployment runs more than one process and the
    cached data must be consistent across them, switch ``CACHE_BACKEND`` to ``redis``.

    Values are stored and returned as serialised copies. Handing back the original
    object would make this backend behave differently from Redis (which necessarily
    round-trips through bytes): a caller that mutated a returned dict would silently
    corrupt the cache here and not in production -- the worst possible split, because
    the bug only appears in the environment where it is hardest to reproduce.
    Serialising also fails loudly on values that Redis could not have stored anyway.
    """

    def __init__(self, *, max_entries: int = 10_000) -> None:
        self._store: dict[str, _Entry] = {}
        self._max_entries = max_entries

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and entry.expires_at <= time.monotonic():
            self._store.pop(key, None)
            return None
        return orjson.loads(entry.value)

    async def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        if len(self._store) >= self._max_entries:
            self._evict()
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        self._store[key] = _Entry(value=orjson.dumps(value), expires_at=expires_at)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def clear_prefix(self, prefix: str) -> None:
        for key in [k for k in self._store if k.startswith(prefix)]:
            self._store.pop(key, None)

    async def close(self) -> None:
        self._store.clear()

    def _evict(self) -> None:
        """Drop expired entries first, then the oldest insertions (dicts keep order)."""
        now = time.monotonic()
        expired = [
            k for k, e in self._store.items() if e.expires_at is not None and e.expires_at <= now
        ]
        for key in expired:
            self._store.pop(key, None)
        while len(self._store) >= self._max_entries:
            self._store.pop(next(iter(self._store)))
