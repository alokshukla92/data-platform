"""Redis-backed async cache with namespacing, TTLs, and tag-based invalidation.

Strategy:
- Cache-aside (lazy) reads via :func:`cached`.
- Versioned namespaces so a single key bump invalidates a whole class of entries
  (e.g. all search results for a tenant after new documents are ingested).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from .config import get_settings
from .telemetry import CACHE_EVENTS_TOTAL

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, encoding="utf-8", decode_responses=True
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _key(namespace: str, *parts: Any) -> str:
    raw = ":".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"cache:{namespace}:{digest}"


async def cache_get(namespace: str, *parts: Any) -> Any | None:
    val = await get_redis().get(_key(namespace, *parts))
    CACHE_EVENTS_TOTAL.labels(result="hit" if val is not None else "miss").inc()
    return json.loads(val) if val is not None else None


async def cache_set(namespace: str, value: Any, *parts: Any, ttl: int | None = None) -> None:
    ttl = ttl if ttl is not None else get_settings().cache_ttl_seconds
    await get_redis().set(_key(namespace, *parts), json.dumps(value, default=str), ex=ttl)


async def invalidate_namespace(namespace: str) -> int:
    """Delete every key in a namespace. Uses SCAN to avoid blocking Redis."""
    client = get_redis()
    pattern = f"cache:{namespace}:*"
    deleted = 0
    async for key in client.scan_iter(match=pattern, count=500):
        await client.delete(key)
        deleted += 1
    return deleted


async def cached(
    namespace: str,
    loader: Callable[[], Awaitable[Any]],
    *parts: Any,
    ttl: int | None = None,
) -> Any:
    """Cache-aside helper: return cached value or populate it via ``loader``."""
    hit = await cache_get(namespace, *parts)
    if hit is not None:
        return hit
    value = await loader()
    await cache_set(namespace, value, *parts, ttl=ttl)
    return value
