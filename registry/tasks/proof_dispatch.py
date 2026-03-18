"""Proof dispatch Celery task — orchestrates the distributed proof pipeline.

Lifecycle: QUEUED → PARTITIONING → DISPATCHED → PROVING → AGGREGATING → VERIFYING → COMPLETED
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)

_DISPATCH_LOCK_TTL_SECONDS = 360


def _build_cumulative_weights(scores: list[float]) -> list[float]:
    normalized = [max(float(s), 0.0) for s in scores]
    total = sum(normalized)
    if not normalized:
        return []
    if total <= 0:
        return [float(i + 1) / float(len(normalized)) for i in range(len(normalized))]

    running = 0.0
    cumulative: list[float] = []
    for score in normalized:
        running += score / total
        cumulative.append(running)
    return cumulative


def _pick_weighted_index(index: int, cumulative_weights: list[float]) -> int:
    if not cumulative_weights:
        return 0
    cursor = ((index * 2654435761) % 10_000) / 10_000.0
    for pos, boundary in enumerate(cumulative_weights):
        if cursor <= boundary:
            return pos
    return len(cumulative_weights) - 1


def _dispatch_lock_key(job_id: int) -> str:
    return f"dispatch_job_{job_id}"


async def _get_dispatch_redis_client():
    from registry.core.cache import cache

    if cache and hasattr(cache, "_redis") and cache._redis:
        return cache._redis
    return None


async def _acquire_dispatch_lock(job_id: int) -> tuple[object | None, str, str | None, bool]:
    redis_client = await _get_dispatch_redis_client()
    lock_key = _dispatch_lock_key(job_id)
    lock_token: str | None = None

    if not redis_client:
        return None, lock_key, lock_token, True

    lock_token = str(uuid.uuid4())
    acquired = await redis_client.set(
        lock_key,
        lock_token,
        nx=True,
        ex=_DISPATCH_LOCK_TTL_SECONDS,
    )
    return redis_client, lock_key, lock_token, bool(acquired)


# Lua script for atomic compare-and-delete to prevent releasing another task's lock
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


async def _release_dispatch_lock(redis_client, lock_key: str, lock_token: str | None) -> None:
    if not redis_client or not lock_token:
        return

    try:
        await redis_client.eval(_RELEASE_LOCK_LUA, 1, lock_key, lock_token)
    except Exception:
        logger.warning("Failed to release dispatch lock for key %s", lock_key, exc_info=True)


def _should_skip_dispatch(job) -> bool:
    from registry.models.database import ProofJobStatus

    return job.status != ProofJobStatus.QUEUED


@app.task(bind=True, name="registry.tasks.proof_dispatch.dispatch_proof_job", max_retries=2, soft_time_limit=300, time_limit=360)
def dispatch_proof_job(self, job_id: int, request_id: str | None = None) -> dict:
    """Main proof dispatch task that partitions a circuit and routes it to provers."""
    try:
        return asyncio.run(_dispatch_with_lock(self, job_id, request_id))
    except Exception as exc:
        try:
            asyncio.run(_timeout_job(job_id, str(exc)))
        except Exception as timeout_exc:
            logger.error("Failed to mark proof job %d as timed out: %s", job_id, timeout_exc)
        raise


async def _dispatch_with_lock(task, job_id: int, request_id: str | None = None) -> dict:
    redis_client, lock_key, lock_token, acquired = await _acquire_dispatch_lock(job_id)
    if not acquired:
        logger.info("Proof job %d dispatch already in progress request_id=%s", job_id, request_id or "")
        return {"status": "skipped_idempotent", "job_id": job_id}

    try:
        return await _dispatch_async(task, job_id, request_id)
    except Exception:
        logger.warning(
            "Proof job %d dispatch failed while lock was held request_id=%s",
            job_id,
            request_id or "",
            exc_info=True,
        )
        raise
    finally:
        await _release_dispatch_lock(redis_client, lock_key, lock_token)


async def _timeout_job(job_id: int, error: str) -> None:
    """Mark a job as timed out when dispatch exceeds time limit."""
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import ProofJobRow, ProofJobStatus, set_proof_job_status

    async with async_session() as db:
        job = (await db.execute(
            select(ProofJobRow).where(ProofJobRow.id == job_id)
        )).scalar_one_or_none()
        if job and job.status not in (ProofJobStatus.COMPLETED, ProofJobStatus.FAILED, ProofJobStatus.TIMEOUT):
            set_proof_job_status(job, ProofJobStatus.FAILED)
            job.error = f"Dispatch timed out: {error[:500]}"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()


async def _dispatch_async(task, job_id: int, request_id: str | None = None) -> dict:
    """Async inner dispatch logic."""
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import (
        ProofJobRow, ProofJobStatus, CircuitRow,
        CircuitPartitionRow, ProverCapabilityRow, set_proof_job_status,
    )
    from registry.core.config import settings

    async with async_session() as db:
        # Load job
        job = (await db.execute(
            select(ProofJobRow).where(ProofJobRow.id == job_id)
        )).scalar_one_or_none()
        if not job:
            logger.error("Proof job %d not found", job_id)
            return {"error": "job not found"}

        if _should_skip_dispatch(job):
            logger.info("Proof job %d already in status %s; skipping duplicate dispatch", job_id, job.status)
            return {
                "job_id": job_id,
                "task_id": job.task_id,
                "status": str(job.status),
                "skipped": True,
            }

        circuit = (await db.execute(
            select(CircuitRow).where(CircuitRow.id == job.circuit_id)
        )).scalar_one_or_none()
        if not circuit:
            await _fail_job(db, job, "Circuit not found")
            return {"error": "circuit not found"}

        try:
            # 1. PARTITIONING
            set_proof_job_status(job, ProofJobStatus.PARTITIONING)
            job.started_at = datetime.now(timezone.utc)
            await db.commit()

            max_per = settings.max_constraints_per_partition
            num_partitions = max(1, (circuit.num_constraints + max_per - 1) // max_per)
            num_partitions = min(num_partitions, settings.max_partitions_per_job)
            constraints_per = (circuit.num_constraints + num_partitions - 1) // num_partitions

            # Create partition records
            for i in range(num_partitions):
                start = i * constraints_per
                end = min((i + 1) * constraints_per, circuit.num_constraints)
                if start >= circuit.num_constraints:
                    break
                partition = CircuitPartitionRow(
                    job_id=job.id,
                    partition_index=i,
                    total_partitions=num_partitions,
                    constraint_start=start,
                    constraint_end=end,
                    status="pending",
                )
                db.add(partition)

            job.num_partitions = num_partitions
            await db.commit()

            # 2. DISPATCHED — assign to online provers
            set_proof_job_status(job, ProofJobStatus.DISPATCHED)
            await db.commit()

            # Find available provers
            provers = (await db.execute(
                select(ProverCapabilityRow)
                .where(ProverCapabilityRow.online == True)
                .order_by(ProverCapabilityRow.benchmark_score.desc())
            )).scalars().all()

            if not provers:
                await _fail_job(db, job, "No online provers available")
                return {"error": "no provers"}

            # Filter provers through anti-sybil gates
            from subnet.reward.anti_sybil import StakeGate, GpuBenchmarkGate
            stake_gate = StakeGate()
            gpu_gate = GpuBenchmarkGate()
            qualified_provers = [
                p for p in provers
                if gpu_gate.check(float(p.benchmark_score or 0.0), p.hotkey)
            ]
            if not qualified_provers:
                # Fallback: use all online provers if none pass GPU gate
                logger.warning(
                    "No provers pass GPU benchmark gate for job %d; using all %d online provers",
                    job_id, len(provers),
                )
                qualified_provers = provers

            # Lock partitions for assignment to prevent races
            partitions = (await db.execute(
                select(CircuitPartitionRow)
                .where(CircuitPartitionRow.job_id == job.id)
                .order_by(CircuitPartitionRow.partition_index)
                .with_for_update()
            )).scalars().all()

            # Load-aware weighted selection: effective_weight = benchmark * (1 - current_load)
            # This prevents overloading slower or busier provers.
            effective_scores = []
            for p in qualified_provers:
                benchmark = float(p.benchmark_score or 0.0)
                load = float(getattr(p, "current_load", 0.0) or 0.0)
                load = min(max(load, 0.0), 1.0)
                effective_scores.append(benchmark * (1.0 - load * 0.8))

            cumulative_weights = _build_cumulative_weights(effective_scores)

            # Track assignments to avoid assigning same partition to same prover
            # when redundancy > 1.
            assigned_per_partition: dict[int, set[str]] = {}
            for i, partition in enumerate(partitions):
                pidx = partition.partition_index
                assigned_per_partition.setdefault(pidx, set())

                # Pick a prover, avoiding duplicates for redundancy
                prover_idx = _pick_weighted_index(i, cumulative_weights)
                prover = qualified_provers[prover_idx]

                if prover.hotkey in assigned_per_partition[pidx] and len(qualified_provers) > 1:
                    # Try next provers to find a non-duplicate
                    for offset in range(1, len(qualified_provers)):
                        alt_idx = (prover_idx + offset) % len(qualified_provers)
                        if qualified_provers[alt_idx].hotkey not in assigned_per_partition[pidx]:
                            prover = qualified_provers[alt_idx]
                            break

                assigned_per_partition[pidx].add(prover.hotkey)
                partition.assigned_prover = prover.hotkey
                partition.status = "assigned"
                partition.assigned_at = datetime.now(timezone.utc)
            await db.commit()

            # 3. PROVING — in production, this triggers miner requests via Bittensor
            set_proof_job_status(job, ProofJobStatus.PROVING)
            await db.commit()

            # The actual proving happens via the subnet:
            # Validators send ProofRequestSynapse to assigned miners
            # Miners return ProofFragment via handle_proof_request
            # This task monitors completion status

            logger.info(
                "Proof job %d dispatched: circuit=%s partitions=%d provers=%d request_id=%s",
                job_id,
                circuit.name,
                num_partitions,
                len(provers),
                request_id or "",
            )

            # Fire webhook for DISPATCHED transition
            try:
                from registry.tasks.webhook_delivery import fire_webhooks_for_job
                await fire_webhooks_for_job(job.id, "proof.dispatched", {
                    "job_id": job.id,
                    "task_id": job.task_id,
                    "circuit_id": circuit.id,
                    "circuit_name": circuit.name,
                    "num_partitions": num_partitions,
                    "provers_assigned": len(provers),
                })
            except Exception as exc:
                logger.debug("Webhook queueing for dispatch failed (non-critical): %s", exc)

            return {
                "job_id": job_id,
                "task_id": job.task_id,
                "status": "dispatched",
                "partitions": num_partitions,
                "request_id": request_id,
            }

        except Exception as exc:
            logger.error("Proof dispatch failed for job %d: %s", job_id, exc)
            await _fail_job(db, job, str(exc))
            raise


async def _fail_job(db, job, error: str) -> None:
    """Mark a job as failed."""
    from registry.models.database import ProofJobStatus, set_proof_job_status

    set_proof_job_status(job, ProofJobStatus.FAILED)
    job.error = error[:2000]  # Truncate to avoid oversized error messages
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()


@app.task(name="registry.tasks.proof_dispatch.complete_proof_job")
def complete_proof_job(job_id: int, proof_data_cid: str, proof_hash: str) -> dict:
    """Called when all partitions are complete — creates the final proof record."""
    return asyncio.run(_complete_async(job_id, proof_data_cid, proof_hash))


async def _complete_async(job_id: int, proof_data_cid: str, proof_hash: str) -> dict:
    import re as _re
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import (
        ProofJobRow, ProofJobStatus, ProofRow, CircuitRow, set_proof_job_status,
    )

    if not _re.match(r'^[a-f0-9]{64}$', proof_hash):
        return {"error": f"Invalid proof hash format: {proof_hash[:80]}"}

    async with async_session() as db:
        job = (await db.execute(
            select(ProofJobRow).where(ProofJobRow.id == job_id)
        )).scalar_one_or_none()
        if not job:
            return {"error": "job not found"}

        circuit = (await db.execute(
            select(CircuitRow).where(CircuitRow.id == job.circuit_id)
        )).scalar_one_or_none()

        # Calculate total time
        now = datetime.now(timezone.utc)
        if job.started_at:
            actual_ms = int((now - job.started_at).total_seconds() * 1000)
        else:
            actual_ms = 0

        # Create proof record
        proof = ProofRow(
            proof_hash=proof_hash,
            circuit_id=job.circuit_id,
            job_id=job.id,
            proof_type=circuit.proof_type if circuit else "groth16",
            proof_data_cid=proof_data_cid,
            public_inputs_json=job.public_inputs_json,
            generation_time_ms=actual_ms,
            prover_hotkey=job.requester_hotkey,
            verified=False,
        )
        db.add(proof)
        await db.flush()

        # Update job
        if job.status != ProofJobStatus.VERIFYING:
            set_proof_job_status(job, ProofJobStatus.VERIFYING)
        set_proof_job_status(job, ProofJobStatus.COMPLETED)
        job.partitions_completed = job.num_partitions
        job.result_proof_id = proof.id
        job.actual_time_ms = actual_ms
        job.completed_at = now

        # Update circuit stats
        if circuit:
            circuit.proofs_generated = (circuit.proofs_generated or 0) + 1

        await db.commit()

        logger.info("Proof job %d completed: proof_hash=%s time=%dms", job_id, proof_hash, actual_ms)
        return {"job_id": job_id, "proof_id": proof.id, "status": "completed"}
