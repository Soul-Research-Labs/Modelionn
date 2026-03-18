"""Periodic Celery tasks — scheduled by celery_app.py beat_schedule."""

from __future__ import annotations

import asyncio
import logging

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="registry.tasks.periodic.reset_daily_api_key_counters", bind=True, time_limit=300, max_retries=3, default_retry_delay=60)
def reset_daily_api_key_counters(self) -> dict:
    """Reset daily usage counters on all API keys (runs at midnight UTC)."""
    return asyncio.run(_reset_counters_async())


async def _reset_counters_async() -> dict:
    from sqlalchemy import update
    from registry.core.deps import async_session
    from registry.models.database import APIKeyRow

    try:
        async with async_session() as db:
            result = await db.execute(
                update(APIKeyRow).where(APIKeyRow.requests_today > 0).values(requests_today=0)
            )
            count = result.rowcount
            await db.commit()
    except Exception as exc:
        logger.error("Failed to reset daily API key counters: %s", exc)
        return {"reset": 0, "error": str(exc)[:200]}

    logger.info("Reset daily counters for %d API key(s)", count)
    return {"reset": count}


# ── Audit log retention ────────────────────────────────────────

_AUDIT_RETENTION_DAYS = 90


@app.task(name="registry.tasks.periodic.purge_old_audit_logs", bind=True, time_limit=600, max_retries=2, default_retry_delay=120)
def purge_old_audit_logs(self) -> dict:
    """Delete audit log entries older than the retention period (default 90 days).

    Runs weekly via beat_schedule.  PII fields (ip_address) are cleared first,
    then the row is deleted to satisfy GDPR right-to-erasure requirements.
    """
    return asyncio.run(_purge_audit_logs_async())


async def _purge_audit_logs_async() -> dict:
    from datetime import timedelta, timezone
    from sqlalchemy import delete
    from registry.core.deps import async_session
    from registry.models.database import AuditLogRow

    cutoff = asyncio.get_event_loop().time()  # not used directly
    from datetime import datetime as _dt
    cutoff_dt = _dt.now(timezone.utc) - timedelta(days=_AUDIT_RETENTION_DAYS)

    try:
        async with async_session() as db:
            result = await db.execute(
                delete(AuditLogRow).where(AuditLogRow.created_at < cutoff_dt)
            )
            count = result.rowcount
            await db.commit()
    except Exception as exc:
        logger.error("Failed to purge audit logs: %s", exc)
        return {"purged": 0, "error": str(exc)[:200]}

    logger.info("Purged %d audit log entries older than %d days", count, _AUDIT_RETENTION_DAYS)
    return {"purged": count, "retention_days": _AUDIT_RETENTION_DAYS}


# Prover ranking refresh is handled by registry.tasks.prover_health.update_prover_rankings
# (scheduled every 30 minutes via beat_schedule).
