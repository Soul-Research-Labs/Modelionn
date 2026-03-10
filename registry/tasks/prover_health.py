"""Prover health monitoring — periodic tasks for tracking prover status."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="registry.tasks.prover_health.check_prover_health")
def check_prover_health() -> dict:
    """Mark provers as offline if they haven't pinged recently."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_check_health_async())
    finally:
        loop.close()


async def _check_health_async() -> dict:
    from sqlalchemy import select, update
    from registry.core.database import async_session
    from registry.models.database import ProverCapabilityRow, CircuitPartitionRow
    from registry.core.config import settings

    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.prover_offline_threshold_s)

    async with async_session() as db:
        # Find provers about to go offline
        going_offline = (await db.execute(
            select(ProverCapabilityRow.hotkey)
            .where(
                ProverCapabilityRow.online == True,
                ProverCapabilityRow.last_ping_at < threshold,
            )
        )).scalars().all()

        # Mark them offline
        result = await db.execute(
            update(ProverCapabilityRow)
            .where(
                ProverCapabilityRow.online == True,
                ProverCapabilityRow.last_ping_at < threshold,
            )
            .values(online=False)
        )
        count = result.rowcount

        # Reassign orphaned partitions from offline provers
        reassigned = 0
        if going_offline:
            orphaned = (await db.execute(
                select(CircuitPartitionRow)
                .where(
                    CircuitPartitionRow.assigned_prover.in_(going_offline),
                    CircuitPartitionRow.status.in_(["assigned", "proving"]),
                )
            )).scalars().all()

            if orphaned:
                # Find an online prover to reassign to
                online_provers = (await db.execute(
                    select(ProverCapabilityRow)
                    .where(ProverCapabilityRow.online == True)
                    .order_by(ProverCapabilityRow.benchmark_score.desc())
                )).scalars().all()

                for partition in orphaned:
                    if online_provers:
                        new_prover = online_provers[reassigned % len(online_provers)]
                        partition.assigned_prover = new_prover.hotkey
                        partition.status = "assigned"
                        partition.assigned_at = datetime.now(timezone.utc)
                        reassigned += 1
                    else:
                        partition.status = "pending"
                        partition.assigned_prover = None
                        reassigned += 1

        await db.commit()

    if count > 0:
        logger.info("Marked %d prover(s) as offline, reassigned %d partition(s)", count, reassigned)

    return {"marked_offline": count, "reassigned_partitions": reassigned}


@app.task(name="registry.tasks.prover_health.update_prover_rankings")
def update_prover_rankings() -> dict:
    """Recalculate prover reliability and ranking scores."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_update_rankings_async())
    finally:
        loop.close()


async def _update_rankings_async() -> dict:
    from sqlalchemy import select
    from registry.core.database import async_session
    from registry.models.database import ProverCapabilityRow

    async with async_session() as db:
        provers = (await db.execute(
            select(ProverCapabilityRow).where(ProverCapabilityRow.total_proofs > 0)
        )).scalars().all()

        updated = 0
        for prover in provers:
            total = prover.total_proofs
            if total > 0:
                success_rate = prover.successful_proofs / total
                prover.uptime_ratio = min(1.0, 0.7 * success_rate + 0.3 * prover.uptime_ratio)
                updated += 1

        await db.commit()

    logger.info("Updated rankings for %d provers", updated)
    return {"updated": updated}


@app.task(name="registry.tasks.prover_health.cleanup_stale_jobs")
def cleanup_stale_jobs() -> dict:
    """Timeout and fail proof jobs that have been running too long."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_cleanup_stale_async())
    finally:
        loop.close()


async def _cleanup_stale_async() -> dict:
    from sqlalchemy import select, update
    from registry.core.database import async_session
    from registry.models.database import ProofJobRow, ProofJobStatus
    from registry.core.config import settings

    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.prover_timeout_s)

    async with async_session() as db:
        result = await db.execute(
            update(ProofJobRow)
            .where(
                ProofJobRow.status.in_([
                    ProofJobStatus.DISPATCHED.value,
                    ProofJobStatus.PROVING.value,
                    ProofJobStatus.AGGREGATING.value,
                ]),
                ProofJobRow.started_at < threshold,
            )
            .values(
                status=ProofJobStatus.TIMEOUT,
                error="Job timed out",
                completed_at=datetime.now(timezone.utc),
            )
        )
        count = result.rowcount
        await db.commit()

    if count > 0:
        logger.warning("Timed out %d stale proof job(s)", count)

    return {"timed_out": count}
