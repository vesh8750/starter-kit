from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis

from app.core.logging import get_logger

log = get_logger(__name__)


class RedisCache:
    """Redis-backed cache.

    Failures are swallowed and logged rather than raised: a cache outage should degrade
    latency, not take the API down. Anything that *must* be consistent belongs in the
    database, not here.
    """

    def __init__(self, client: Redis, *, default_ttl_seconds: int = 300) -> None:
        self._client = client
        self._default_ttl = default_ttl_seconds

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            log.warning("cache.get_failed", key=key, error=str(exc))
            return None
        return orjson.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        try:
            await self._client.set(key, orjson.dumps(value), ex=ttl_seconds or self._default_ttl)
        except Exception as exc:
            log.warning("cache.set_failed", key=key, error=str(exc))

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            await self._client.delete(*keys)
        except Exception as exc:
            log.warning("cache.delete_failed", error=str(exc))

    async def clear_prefix(self, prefix: str) -> None:
        """SCAN, never KEYS -- KEYS blocks the Redis event loop on large keyspaces."""
        try:
            async for key in self._client.scan_iter(match=f"{prefix}*", count=500):
                await self._client.delete(key)
        except Exception as exc:
            log.warning("cache.clear_prefix_failed", prefix=prefix, error=str(exc))

    async def close(self) -> None:
        await self._client.aclose()
