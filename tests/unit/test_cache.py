from __future__ import annotations

from app.cache.base import cache_key
from app.cache.memory import InMemoryCache


async def test_set_get_delete():
    cache = InMemoryCache()
    await cache.set("a", {"v": 1})
    assert await cache.get("a") == {"v": 1}
    await cache.delete("a")
    assert await cache.get("a") is None


async def test_expired_entries_are_not_returned():
    cache = InMemoryCache()
    await cache.set("a", 1, ttl_seconds=0)
    assert await cache.get("a") is None


async def test_clear_prefix_only_removes_the_namespace():
    cache = InMemoryCache()
    await cache.set("pets:1", 1)
    await cache.set("owners:1", 1)
    await cache.clear_prefix("pets:")
    assert await cache.get("pets:1") is None
    assert await cache.get("owners:1") == 1


def test_long_keys_are_hashed_to_stay_bounded():
    key = cache_key("pets", "x" * 200)
    assert len(key) < 80
    assert key == cache_key("pets", "x" * 200)
