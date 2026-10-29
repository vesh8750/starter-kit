from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.cache.base import Cache
from app.cache.memory import InMemoryCache
from app.core.config import Settings

_cache: Cache | None = None


def build_cache(settings: Settings) -> Cache:
    if settings.cache_backend == "redis":
        from redis.asyncio import Redis  # imported lazily: optional in some deployments

        from app.cache.redis import RedisCache

        client = Redis.from_url(str(settings.redis_url), decode_responses=False)
        return RedisCache(client, default_ttl_seconds=settings.cache_default_ttl_seconds)
    return InMemoryCache()


def init_cache(settings: Settings) -> Cache:
    global _cache
    if _cache is None:
        _cache = build_cache(settings)
    return _cache


async def dispose_cache() -> None:
    global _cache
    if _cache is not None:
        await _cache.close()
    _cache = None


def get_cache() -> Cache:
    if _cache is None:
        raise RuntimeError("Cache is not initialised; call init_cache() first.")
    return _cache


CacheDep = Annotated[Cache, Depends(get_cache)]
