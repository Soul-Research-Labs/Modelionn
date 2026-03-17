"""Prover health monitoring — periodic tasks for tracking prover status."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)


def _recover_orphaned_partition(partition, online_provers: list, index: int) -> str:
    """Safely recover a partition assigned to a prover that just went offline."""
    original_status = partition.status
    if partition.status == "assigned" and online_provers:
        new_prover = online_provers[index % len(online_provers)]
        partition.assigned_prover = new_prover.hotkey
        partition.status = "assigned"
        partition.assigned_at = datetime.now(timezone.utc)
        partition.error = "Reassigned after assigned prover went offline"
        return "reassigned"

    partition.status = "pending"
    partition.assigned_prover = None
    partition.assigned_at = None
    if original_status == "proving":
        partition.error = "Reset after assigned prover went offline during proving"
    else:
        partition.error = "Reset after assigned prover went offline"
    return "reset"


def _resolve_stale_job_target(status) -> str:
    from registry.models.database import ProofJobStatus

    current = status if isinstance(status, ProofJobStatus) else ProofJobStatus(status)
    if current == ProofJobStatus.PROVING:
        return ProofJobStatus.TIMEOUT
    return ProofJobStatus.FAILED


@app.task(name="registry.tasks.prover_health.check_prover_health", bind=True, time_limit=120, max_retries=2, default_retry_delay=30)
def check_prover_health(self) -> dict:
    """Mark provers as offline if they haven't pinged recently."""
    return asyncio.run(_check_health_async())


async def _check_health_async() -> dict:
    from sqlalchemy import select, update
    from registry.core.deps import async_session
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
        reset_to_pending = 0
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
                    action = _recover_orphaned_partition(partition, online_provers, reassigned)
                    if action == "reassigned":
                        reassigned += 1
                    else:
                        reset_to_pending += 1

        await db.commit()

    if count > 0:
        logger.info(
            "Marked %d prover(s) as offline, reassigned %d partition(s), reset %d to pending",
            count,
            reassigned,
            reset_to_pending,
        )

    return {
        "marked_offline": count,
        "reassigned_partitions": reassigned,
        "reset_partitions": reset_to_pending,
    }


@app.task(name="registry.tasks.prover_health.update_prover_rankings", bind=True, time_limit=300, max_retries=2, default_retry_delay=60)
def update_prover_rankings(self) -> dict:
    """Recalculate prover reliability and ranking scores."""
    return asyncio.run(_update_rankings_async())


async def _update_rankings_async() -> dict:
    from sqlalchemy import select
    from registry.core.deps import async_session
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


@app.task(name="registry.tasks.prover_health.cleanup_stale_jobs", bind=True, time_limit=180, max_retries=2, default_retry_delay=30)
def cleanup_stale_jobs(self) -> dict:
    """Timeout and fail proof jobs that have been running too long."""
    return asyncio.run(_cleanup_stale_async())


async def _cleanup_stale_async() -> dict:
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import ProofJobRow, ProofJobStatus, set_proof_job_status
    from registry.core.config import settings

    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.prover_timeout_s)

    async with async_session() as db:
        jobs = (
            await db.execute(
                select(ProofJobRow)
                .where(
                    ProofJobRow.status.in_([
                        ProofJobStatus.DISPATCHED.value,
                        ProofJobStatus.PROVING.value,
                        ProofJobStatus.AGGREGATING.value,
                    ]),
                    ProofJobRow.started_at < threshold,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        count = 0
        for job in jobs:
            target_status = _resolve_stale_job_target(job.status)
            set_proof_job_status(job, target_status)
            if target_status == ProofJobStatus.TIMEOUT:
                job.error = "Job timed out"
            else:
                job.error = "Job exceeded stale threshold before completion"
            job.completed_at = datetime.now(timezone.utc)
            count += 1
        await db.commit()

    if count > 0:
        logger.warning("Timed out %d stale proof job(s)", count)

    return {"timed_out": count}
