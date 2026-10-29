"""Caching.

Business code depends on the :class:`~app.cache.base.Cache` protocol, never on Redis.
The default backend is in-process (correct for a single instance, and for tests); Redis
is a configuration change, not a code change.
"""

from app.cache.base import Cache, cache_key
from app.cache.factory import build_cache, get_cache

__all__ = ["Cache", "build_cache", "cache_key", "get_cache"]
