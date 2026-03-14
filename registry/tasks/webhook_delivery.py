"""Webhook delivery task — sends event payloads to configured webhook endpoints.

Fires on proof job state changes (COMPLETED, FAILED, TIMEOUT, CANCELLED).
Uses HMAC-SHA256 signing so recipients can verify payload authenticity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)

_DELIVERY_TIMEOUT = 10  # seconds per delivery attempt
_MAX_RETRIES = 3


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


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
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_deliver(self, webhook_id, event, payload))
    finally:
        loop.close()


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
                        "X-Modelionn-Signature": f"sha256={signature}",
                        "X-Modelionn-Event": event,
                    },
                )
                resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning(
                "Webhook delivery failed for %d (attempt %d/%d): %s",
                webhook_id, (task.request.retries or 0) + 1, _MAX_RETRIES, exc,
            )
            raise

        # Update last_triggered_at
        row.last_triggered_at = datetime.now(timezone.utc)
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
