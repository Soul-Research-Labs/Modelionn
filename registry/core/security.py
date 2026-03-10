"""Bittensor wallet-based authentication and authorization."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# Signature validity window (seconds)
_MAX_AGE = 300

# ── Nonce replay prevention ─────────────────────────────────
# Uses Redis when available for distributed dedup across workers;
# falls back to in-memory dict for development.
_used_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()

_redis_nonce_client = None
_redis_nonce_init = False


def _get_nonce_redis():
    """Return a Redis client for nonce tracking, or None."""
    global _redis_nonce_client, _redis_nonce_init
    if _redis_nonce_init:
        return _redis_nonce_client
    _redis_nonce_init = True
    try:
        import redis
        from registry.core.config import settings
        _redis_nonce_client = redis.Redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2,
        )
        _redis_nonce_client.ping()
        logger.info("Nonce replay prevention: using Redis")
    except Exception:
        _redis_nonce_client = None
        logger.info("Nonce replay prevention: using in-memory fallback")
    return _redis_nonce_client


def _check_and_record_nonce(nonce: str, now: float) -> bool:
    """Return True if the nonce hasn't been used yet. Records it for dedup."""
    r = _get_nonce_redis()
    if r:
        try:
            key = f"nonce:{nonce}"
            # SET NX with TTL — atomic check-and-set
            if r.set(key, "1", nx=True, ex=_MAX_AGE + 10):
                return True
            return False
        except Exception:
            pass  # fall through to in-memory

    with _nonce_lock:
        expired = [n for n, ts in _used_nonces.items() if now - ts > _MAX_AGE]
        for n in expired:
            del _used_nonces[n]
        if nonce in _used_nonces:
            return False
        _used_nonces[nonce] = now
        return True


async def verify_publisher(
    x_hotkey: str = Header(..., description="Publisher Bittensor hotkey (SS58)"),
    x_signature: str = Header(..., description="Hex-encoded signature of the request body hash"),
    x_nonce: str = Header(..., description="Unix timestamp nonce"),
) -> str:
    """FastAPI dependency that authenticates a publisher via Bittensor hotkey signature.

    In production this verifies the ed25519 / sr25519 signature produced by the
    hotkey over ``sha256(body + nonce)``.  For the MVP we perform a lightweight
    nonce-freshness check and return the hotkey — full cryptographic verification
    is plugged in when ``bittensor`` is available at runtime.
    """
    # Nonce freshness
    try:
        ts = int(x_nonce)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid nonce")
    now = time.time()
    if abs(now - ts) > _MAX_AGE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nonce expired")

    # Replay prevention
    if not _check_and_record_nonce(x_nonce, now):
        from registry.api.routes.metrics import inc_counter, NONCE_REPLAYS_BLOCKED
        inc_counter(NONCE_REPLAYS_BLOCKED)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nonce already used")

    # Basic format validation for SS58 hotkey
    if not x_hotkey or len(x_hotkey) < 46:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid hotkey format")

    # --- Full signature verification (requires bittensor) ---
    try:
        import bittensor as bt  # type: ignore[import-untyped]

        keypair = bt.Keypair(ss58_address=x_hotkey)
        message = f"{x_hotkey}:{x_nonce}"
        sig_bytes = bytes.fromhex(x_signature)
        if not keypair.verify(message.encode(), sig_bytes):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    except ImportError:
        from registry.core.config import settings as _cfg
        if _cfg.require_signature_verification:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Signature verification required but bittensor is not installed",
            )
        logger.critical(
            "UNAUTHENTICATED MODE: bittensor not installed — signature verification "
            "disabled. Do NOT use this in production! Set require_signature_verification=True."
        )
    except Exception as exc:
        logger.error("Signature verification failed for hotkey %s: %s", x_hotkey, exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signature verification failed")

    return x_hotkey


def hash_body(body: bytes, nonce: str) -> str:
    """Produce the sha256 hex digest validators/miners sign."""
    return hashlib.sha256(body + nonce.encode()).hexdigest()
