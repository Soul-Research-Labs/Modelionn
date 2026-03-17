"""API gateway middleware — rate limiting and request counting.

Uses Redis for distributed counting when available, falling back to
in-memory tracking for development.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from registry.core.config import settings

logger = logging.getLogger(__name__)

# In-memory fallback (dev only)
_request_counts: dict[str, list[float]] = defaultdict(list)
_last_cleanup: float = 0.0
_request_counts_lock = Lock()

EXEMPT_PATHS = {"/health", "/health/ready", "/docs", "/openapi.json", "/redoc", "/metrics"}

_CLEANUP_INTERVAL = 300

# Concurrent connection limit per client (prevents connection exhaustion)
_MAX_CONCURRENT_PER_CLIENT = 50
_active_connections: dict[str, int] = defaultdict(int)
_active_connections_lock = Lock()

# Redis client — lazily initialised
_redis_client = None
_redis_init_attempted = False


def _get_redis():
    """Return a Redis client, or None if unavailable."""
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    try:
        import redis
        _redis_client = redis.Redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2,
        )
        _redis_client.ping()
        logger.info("Rate limiter: using Redis at %s", settings.redis_url)
    except Exception as exc:
        _redis_client = None
        if not settings.debug:
            raise RuntimeError(
                "Redis is required for rate limiting in production mode "
                f"(debug=False). Redis connection failed: {exc}"
            ) from exc
        logger.warning(
            "Rate limiter: Redis unavailable, using in-memory fallback. "
            "WARNING: In-memory rate limiting is NOT cluster-safe — each worker "
            "tracks limits independently. Use Redis in production."
        )
    return _redis_client


def _cleanup_stale_buckets() -> None:
    """Remove client buckets with no recent requests to prevent memory leaks."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    window = settings.rate_limit_window
    cutoff = now - window
    stale = [k for k, v in _request_counts.items() if not v or v[-1] < cutoff]
    for k in stale:
        del _request_counts[k]


def _rate_check_redis(client_hash: str, window: int, max_requests: int) -> tuple[bool, int]:
    """Sliding-window rate check via Redis sorted set. Returns (allowed, remaining)."""
    r = _get_redis()
    key = f"rl:{client_hash}"
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zcard(key)
    pipe.zadd(key, {f"{now}": now})
    pipe.expire(key, window + 1)
    _, count, *_ = pipe.execute()
    if count >= max_requests:
        return False, 0
    return True, max_requests - count - 1


def _rate_check_memory(client_hash: str, window: int, max_requests: int) -> tuple[bool, int]:
    """In-memory sliding-window rate check. Returns (allowed, remaining)."""
    now = time.time()
    window_start = now - window
    with _request_counts_lock:
        _request_counts[client_hash] = [
            t for t in _request_counts[client_hash] if t > window_start
        ]
        _cleanup_stale_buckets()
        if len(_request_counts[client_hash]) >= max_requests:
            return False, 0
        _request_counts[client_hash].append(now)
        remaining = max_requests - len(_request_counts[client_hash])
        return True, remaining


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        window = settings.rate_limit_window
        max_requests = settings.rate_limit_max

        # Extract client IP securely:
        # Use the rightmost IP from X-Forwarded-For that isn't from a trusted proxy.
        # If not behind a proxy, use the direct client IP.
        # This prevents spoofing: attackers can prepend fake IPs, but the rightmost
        # entry before the proxy is the real client.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",")]
            # Rightmost IP is the one set by the closest trusted proxy
            client_ip = ips[-1] if ips else "unknown"
        else:
            client_ip = request.client.host if request.client else "unknown"
        client_id = request.headers.get("x-api-key", "") or client_ip
        client_hash = hashlib.sha256(client_id.encode()).hexdigest()[:16]

        if _get_redis():
            try:
                allowed, remaining = _rate_check_redis(client_hash, window, max_requests)
            except Exception:
                allowed, remaining = _rate_check_memory(client_hash, window, max_requests)
        else:
            allowed, remaining = _rate_check_memory(client_hash, window, max_requests)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # Concurrent connection limit — prevent a single client from exhausting
        # server connections.  Uses a simple in-process counter.
        with _active_connections_lock:
            if _active_connections[client_hash] >= _MAX_CONCURRENT_PER_CLIENT:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many concurrent requests. Slow down."},
                    headers={"Retry-After": "1"},
                )
            _active_connections[client_hash] += 1

        try:
            response = await call_next(request)
        finally:
            with _active_connections_lock:
                _active_connections[client_hash] = max(0, _active_connections[client_hash] - 1)

        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
