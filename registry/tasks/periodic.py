"""Periodic Celery tasks — scheduled by celery_app.py beat_schedule."""

from __future__ import annotations

import logging

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="registry.tasks.periodic.reset_daily_api_key_counters", bind=True, time_limit=300, max_retries=3, default_retry_delay=60)
def reset_daily_api_key_counters(self) -> dict:
    """Reset daily usage counters on all API keys (runs at midnight UTC)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_reset_counters_async())
    finally:
        loop.close()


async def _reset_counters_async() -> dict:
    from sqlalchemy import update
    from registry.core.deps import async_session
    from registry.models.database import APIKeyRow

    async with async_session() as db:
        result = await db.execute(
            update(APIKeyRow).where(APIKeyRow.requests_today > 0).values(requests_today=0)
        )
        count = result.rowcount
        await db.commit()

    logger.info("Reset daily counters for %d API key(s)", count)
    return {"reset": count}


@app.task(name="registry.tasks.periodic.refresh_prover_rankings", bind=True, time_limit=600, max_retries=2, default_retry_delay=120)
def refresh_prover_rankings(self) -> dict:
    """Recompute aggregate prover scores (runs every 6 hours)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_refresh_rankings_async())
    finally:
        loop.close()


async def _refresh_rankings_async() -> dict:
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import ProverCapabilityRow

    async with async_session() as db:
        provers = (
            await db.execute(
                select(ProverCapabilityRow).where(ProverCapabilityRow.total_proofs > 0)
            )
        ).scalars().all()

        updated = 0
        for prover in provers:
            total = prover.total_proofs
            if total > 0:
                success_rate = prover.successful_proofs / total
                # Weighted blend: 70% success rate + 30% historical uptime
                prover.uptime_ratio = min(1.0, 0.7 * success_rate + 0.3 * prover.uptime_ratio)
                updated += 1

        await db.commit()

    logger.info("Refreshed rankings for %d prover(s)", updated)
    return {"updated": updated}
