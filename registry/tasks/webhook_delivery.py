"""Webhook delivery task — sends event payloads to configured webhook endpoints.

Fires on proof job state changes (COMPLETED, FAILED, TIMEOUT, CANCELLED).
Uses HMAC-SHA256 signing so recipients can verify payload authenticity.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from threading import Lock
import time

import httpx

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)

_DELIVERY_TIMEOUT = 10  # seconds per delivery attempt
_MAX_RETRIES = 3
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_OPEN_SECONDS = 300

# In-process circuit breaker fallback (worker-local).
_cb_lock = Lock()
_cb_failures: dict[int, int] = {}
_cb_open_until: dict[int, float] = {}

# Dead-letter queue logger — permanently failed deliveries are logged here
# so operators can replay them later.
_dlq_logger = logging.getLogger("zkml.webhook.dlq")


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


async def _get_cb_redis():
    """Return a Redis client for distributed circuit breaker, or None."""
    try:
        from registry.core.cache import cache
        if cache and hasattr(cache, "_redis") and cache._redis:
            return cache._redis
    except Exception:
        pass
    return None


def _is_circuit_open(webhook_id: int, now: float | None = None) -> bool:
    now_ts = now if now is not None else time.time()
    with _cb_lock:
        until = _cb_open_until.get(webhook_id, 0.0)
        if until <= now_ts:
            _cb_open_until.pop(webhook_id, None)
            return False
        return True


async def _is_circuit_open_distributed(webhook_id: int) -> bool:
    """Check distributed circuit breaker state via Redis."""
    redis_client = await _get_cb_redis()
    if redis_client:
        try:
            open_until = await redis_client.get(f"cb:open:{webhook_id}")
            if open_until and float(open_until) > time.time():
                return True
            return False
        except Exception:
            pass
    return _is_circuit_open(webhook_id)


def _record_delivery_failure(webhook_id: int) -> bool:
    """Record failed delivery. Returns True if breaker transitions to open."""
    now_ts = time.time()
    with _cb_lock:
        failures = _cb_failures.get(webhook_id, 0) + 1
        _cb_failures[webhook_id] = failures
        if failures >= _CIRCUIT_FAILURE_THRESHOLD:
            _cb_open_until[webhook_id] = now_ts + _CIRCUIT_OPEN_SECONDS
            return True
        return False


async def _record_delivery_failure_distributed(webhook_id: int) -> bool:
    """Record failure in Redis. Returns True if breaker trips."""
    redis_client = await _get_cb_redis()
    if redis_client:
        try:
            key = f"cb:failures:{webhook_id}"
            failures = await redis_client.incr(key)
            await redis_client.expire(key, _CIRCUIT_OPEN_SECONDS + 60)
            if failures >= _CIRCUIT_FAILURE_THRESHOLD:
                await redis_client.set(
                    f"cb:open:{webhook_id}",
                    str(time.time() + _CIRCUIT_OPEN_SECONDS),
                    ex=_CIRCUIT_OPEN_SECONDS + 10,
                )
                return True
            return False
        except Exception:
            pass
    return _record_delivery_failure(webhook_id)


def _record_delivery_success(webhook_id: int) -> None:
    with _cb_lock:
        _cb_failures.pop(webhook_id, None)
        _cb_open_until.pop(webhook_id, None)


async def _record_delivery_success_distributed(webhook_id: int) -> None:
    """Clear distributed circuit breaker state on success."""
    redis_client = await _get_cb_redis()
    if redis_client:
        try:
            await redis_client.delete(f"cb:failures:{webhook_id}", f"cb:open:{webhook_id}")
        except Exception:
            pass
    _record_delivery_success(webhook_id)


def _log_to_dlq(webhook_id: int, event: str, payload: dict, error: str) -> None:
    """Log permanently failed deliveries to the DLQ logger for operator replay."""
    _dlq_logger.error(
        "DLQ: webhook_id=%d event=%s error=%s payload=%s",
        webhook_id, event, error, json.dumps(payload, default=str)[:2000],
    )


@app.task(
    bind=True,
    name="registry.tasks.webhook_delivery.deliver_webhook",
    max_retries=_MAX_RETRIES,
    default_retry_delay=10,
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    retry_backoff=True,
    retry_backoff_max=60,
)
def deliver_webhook(self, webhook_id: int, event: str, payload: dict) -> dict:
    """Deliver a single webhook event to the configured endpoint.

    Args:
        webhook_id: ID of the WebhookConfigRow.
        event: Event type string (e.g. 'proof.completed').
        payload: JSON-serializable event data.

    Returns:
        Delivery result dict with status and response code.
    """
    return asyncio.run(_deliver(self, webhook_id, event, payload))


async def _deliver(task, webhook_id: int, event: str, payload: dict) -> dict:
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import WebhookConfigRow
    from datetime import datetime, timezone

    async with async_session() as db:
        row = (
            await db.execute(
                select(WebhookConfigRow).where(
                    WebhookConfigRow.id == webhook_id,
                    WebhookConfigRow.active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if not row:
            logger.warning("Webhook %d not found or inactive — skipping delivery", webhook_id)
            return {"status": "skipped", "reason": "not_found_or_inactive"}

        if await _is_circuit_open_distributed(webhook_id):
            logger.warning(
                "Webhook %d circuit is open; skipping delivery for event=%s",
                webhook_id,
                event,
            )
            return {"status": "skipped", "reason": "circuit_open"}

        envelope = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "webhook_id": webhook_id,
            "data": payload,
        }
        body = json.dumps(envelope, default=str).encode()
        signature = _sign_payload(body, row.secret)

        try:
            async with httpx.AsyncClient(timeout=_DELIVERY_TIMEOUT) as client:
                resp = await client.post(
                    row.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-ZKML-Signature": f"sha256={signature}",
                        "X-ZKML-Event": event,
                    },
                )
                resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.HTTPError, httpx.TimeoutException) as exc:
            tripped = await _record_delivery_failure_distributed(webhook_id)
            current_attempt = (task.request.retries or 0) + 1
            logger.warning(
                "Webhook delivery failed for %d (attempt %d/%d): %s",
                webhook_id, current_attempt, _MAX_RETRIES, exc,
            )
            if tripped:
                row.active = False
                await db.commit()
                _log_to_dlq(webhook_id, event, payload, str(exc))
                logger.error(
                    "Webhook %d disabled after %d consecutive failures; logged to DLQ",
                    webhook_id,
                    _CIRCUIT_FAILURE_THRESHOLD,
                )
                return {"status": "disabled", "reason": "circuit_opened"}
            if current_attempt >= _MAX_RETRIES:
                _log_to_dlq(webhook_id, event, payload, f"Exhausted {_MAX_RETRIES} retries: {exc}")
            raise

        # Update last_triggered_at
        row.last_triggered_at = datetime.now(timezone.utc)
        await _record_delivery_success_distributed(webhook_id)
        await db.commit()

        logger.info("Webhook %d delivered: event=%s status=%d", webhook_id, event, resp.status_code)
        return {"status": "delivered", "status_code": resp.status_code}


async def fire_webhooks_for_job(job_id: int, event: str, payload: dict) -> int:
    """Queue webhook deliveries for all active webhooks matching the event.

    Call this from proof_aggregate or other code when a job changes state.

    Args:
        job_id: The proof job ID (used to find the requester's webhooks).
        event: Event type (e.g. 'proof.completed', 'proof.failed').
        payload: Event data dict.

    Returns:
        Number of webhook deliveries queued.
    """
    from sqlalchemy import select, or_
    from registry.core.deps import async_session
    from registry.models.database import WebhookConfigRow, ProofJobRow

    async with async_session() as db:
        # Find the job's requester
        job = (
            await db.execute(
                select(ProofJobRow).where(ProofJobRow.id == job_id)
            )
        ).scalar_one_or_none()
        if not job:
            return 0

        # Find active webhooks for this requester that match the event
        webhooks = (
            await db.execute(
                select(WebhookConfigRow).where(
                    WebhookConfigRow.hotkey == job.requester_hotkey,
                    WebhookConfigRow.active.is_(True),
                    or_(
                        WebhookConfigRow.events == "*",
                        WebhookConfigRow.events.contains(event),
                    ),
                )
            )
        ).scalars().all()

        queued = 0
        for wh in webhooks:
            deliver_webhook.delay(wh.id, event, payload)
            queued += 1

        return queued
