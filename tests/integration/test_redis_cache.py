"""The Redis cache backend.

Coverage here was inverted at review time: the in-memory backend used only in
development was well tested, while the backend that actually runs in production had
none. These tests exercise the real client against a real Redis and skip cleanly when
one is not available, so they run in CI and on a laptop without becoming flaky.
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from app.cache.redis import RedisCache
from app.core.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_cache():
    settings = Settings(_env_file=None)
    client: Redis = Redis.from_url(str(settings.redis_url), decode_responses=False)
    try:
        await client.ping()
    except Exception:  # any connection problem means "no Redis here"
        await client.aclose()
        pytest.skip("Redis is not reachable; skipping the Redis backend tests.")
    cache = RedisCache(client, default_ttl_seconds=60)
    yield cache
    await client.flushdb()
    await cache.close()


async def test_round_trip_preserves_structure(redis_cache: RedisCache):
    key = f"test:{uuid.uuid4()}"
    await redis_cache.set(key, {"a": [1, 2], "b": {"c": True}})
    assert await redis_cache.get(key) == {"a": [1, 2], "b": {"c": True}}


async def test_missing_key_returns_none(redis_cache: RedisCache):
    assert await redis_cache.get(f"test:{uuid.uuid4()}") is None


async def test_delete_removes_the_entry(redis_cache: RedisCache):
    key = f"test:{uuid.uuid4()}"
    await redis_cache.set(key, 1)
    await redis_cache.delete(key)
    assert await redis_cache.get(key) is None


async def test_clear_prefix_only_removes_its_namespace(redis_cache: RedisCache):
    marker = uuid.uuid4().hex
    await redis_cache.set(f"pets:{marker}:1", 1)
    await redis_cache.set(f"pets:{marker}:2", 2)
    await redis_cache.set(f"owners:{marker}:1", 3)

    await redis_cache.clear_prefix(f"pets:{marker}")

    assert await redis_cache.get(f"pets:{marker}:1") is None
    assert await redis_cache.get(f"pets:{marker}:2") is None
    assert await redis_cache.get(f"owners:{marker}:1") == 3


async def test_a_cache_outage_degrades_latency_rather_than_failing_the_request():
    """A dead cache must never turn a working request into a 500."""
    broken: Redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.05)
    cache = RedisCache(broken, default_ttl_seconds=60)

    assert await cache.get("anything") is None  # swallowed and logged
    await cache.set("anything", {"v": 1})  # must not raise
    await cache.delete("anything")
    await cache.clear_prefix("anything")


async def test_in_memory_and_redis_agree_on_value_semantics(redis_cache: RedisCache):
    """Both backends must return copies, so a caller mutating a result cannot
    poison the cache in one environment and not the other."""
    from app.cache.memory import InMemoryCache

    key = f"test:{uuid.uuid4()}"
    for cache in (redis_cache, InMemoryCache()):
        await cache.set(key, {"count": 1})
        got = await cache.get(key)
        assert got is not None
        got["count"] = 999
        assert (await cache.get(key)) == {"count": 1}
