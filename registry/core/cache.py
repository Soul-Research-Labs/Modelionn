"""Redis cache layer — async client with TTL-based caching.

Provides a thin cache abstraction over Redis. Falls back to a no-op
in-memory stub when Redis is unavailable (dev/test convenience).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from registry.core.config import settings

logger = logging.getLogger(__name__)

# Lazy singleton — initialized on first use
_client: Any = None
_fallback_mode = False


async def _get_redis():  # type: ignore[no-untyped-def]
    """Lazily connect to Redis. Returns None if unavailable."""
    global _client, _fallback_mode
    if _client is not None:
        return _client
    if _fallback_mode:
        return None
    try:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        # Verify connection
        await _client.ping()
        logger.info("Redis connected: %s", settings.redis_url)
        return _client
    except Exception:
        logger.warning("Redis unavailable — cache operating in passthrough mode")
        _fallback_mode = True
        return None


async def cache_get(key: str) -> Any | None:
    """Retrieve a cached value. Returns None on miss or Redis unavailability."""
    r = await _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Store a value in cache with TTL."""
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.setex(key, ttl_seconds, json.dumps(value))
    except Exception:
        pass  # Best-effort caching


async def cache_delete(key: str) -> None:
    """Invalidate a cache entry."""
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass


async def cache_health() -> dict:
    """Check if Redis is reachable. Returns status dict."""
    r = await _get_redis()
    if r is None:
        return {"status": "degraded", "detail": "Redis unavailable — passthrough mode"}
    try:
        pong = await r.ping()
        return {"status": "healthy"} if pong else {"status": "degraded", "detail": "ping failed"}
    except Exception as exc:
        return {"status": "degraded", "detail": str(exc)}
