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


# Prover ranking refresh is handled by registry.tasks.prover_health.update_prover_rankings
# (scheduled every 30 minutes via beat_schedule).
