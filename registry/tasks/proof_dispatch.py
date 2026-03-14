"""Proof dispatch Celery task — orchestrates the distributed proof pipeline.

Lifecycle: QUEUED → PARTITIONING → DISPATCHED → PROVING → AGGREGATING → VERIFYING → COMPLETED
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(bind=True, name="registry.tasks.proof_dispatch.dispatch_proof_job", max_retries=2, soft_time_limit=300, time_limit=360)
def dispatch_proof_job(self, job_id: int) -> dict:
    """Main proof dispatch task — partitions circuit and routes to provers.

    This runs synchronously in a Celery worker. It updates the DB
    at each stage of the pipeline.
    """
    try:
        return asyncio.run(_dispatch_async(self, job_id))
    except Exception as exc:
        # Handle soft time limit exceeded — mark job as failed
        try:
            asyncio.run(_timeout_job(job_id, str(exc)))
        except Exception as timeout_exc:
            logger.error("Failed to mark proof job %d as timed out: %s", job_id, timeout_exc)
        raise


async def _timeout_job(job_id: int, error: str) -> None:
    """Mark a job as timed out when dispatch exceeds time limit."""
    from sqlalchemy import select
    from registry.core.deps import async_session
    from registry.models.database import ProofJobRow, ProofJobStatus

    async with async_session() as db:
        job = (await db.execute(
            select(ProofJobRow).where(ProofJobRow.id == job_id)
        )).scalar_one_or_none()
        if job and job.status not in (ProofJobStatus.COMPLETED, ProofJobStatus.FAILED, ProofJobStatus.TIMEOUT):
            job.status = ProofJobStatus.FAILED
            job.error = f"Dispatch timed out: {error[:500]}"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()


async def _dispatch_async(task, job_id: int) -> dict:
    """Async inner dispatch logic."""
    from sqlalchemy import select, update
    from registry.core.deps import async_session
    from registry.models.database import (
        ProofJobRow, ProofJobStatus, CircuitRow,
        CircuitPartitionRow, ProofRow, ProverCapabilityRow,
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

        circuit = (await db.execute(
            select(CircuitRow).where(CircuitRow.id == job.circuit_id)
        )).scalar_one_or_none()
        if not circuit:
            await _fail_job(db, job, "Circuit not found")
            return {"error": "circuit not found"}

        try:
            # 1. PARTITIONING
            job.status = ProofJobStatus.PARTITIONING
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
            job.status = ProofJobStatus.DISPATCHED
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

            # Lock partitions for assignment to prevent races
            partitions = (await db.execute(
                select(CircuitPartitionRow)
                .where(CircuitPartitionRow.job_id == job.id)
                .order_by(CircuitPartitionRow.partition_index)
                .with_for_update()
            )).scalars().all()

            for i, partition in enumerate(partitions):
                prover = provers[i % len(provers)]
                partition.assigned_prover = prover.hotkey
                partition.status = "assigned"
                partition.assigned_at = datetime.now(timezone.utc)
            await db.commit()

            # 3. PROVING — in production, this triggers miner requests via Bittensor
            job.status = ProofJobStatus.PROVING
            await db.commit()

            # The actual proving happens via the subnet:
            # Validators send ProofRequestSynapse to assigned miners
            # Miners return ProofFragment via handle_proof_request
            # This task monitors completion status

            logger.info(
                "Proof job %d dispatched: circuit=%s partitions=%d provers=%d",
                job_id, circuit.name, num_partitions, len(provers),
            )

            return {
                "job_id": job_id,
                "task_id": job.task_id,
                "status": "dispatched",
                "partitions": num_partitions,
            }

        except Exception as exc:
            logger.error("Proof dispatch failed for job %d: %s", job_id, exc)
            await _fail_job(db, job, str(exc))
            raise


async def _fail_job(db, job, error: str) -> None:
    """Mark a job as failed."""
    from registry.models.database import ProofJobStatus
    job.status = ProofJobStatus.FAILED
    job.error = error[:2000]  # Truncate to avoid oversized error messages
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()


@app.task(name="registry.tasks.proof_dispatch.complete_proof_job")
def complete_proof_job(job_id: int, proof_data_cid: str, proof_hash: str) -> dict:
    """Called when all partitions are complete — creates the final proof record."""
    return asyncio.run(_complete_async(job_id, proof_data_cid, proof_hash))


async def _complete_async(job_id: int, proof_data_cid: str, proof_hash: str) -> dict:
    import re as _re
    from sqlalchemy import select, update
    from registry.core.deps import async_session
    from registry.models.database import (
        ProofJobRow, ProofJobStatus, ProofRow, CircuitRow, CircuitPartitionRow,
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
        job.status = ProofJobStatus.COMPLETED
        job.result_proof_id = proof.id
        job.actual_time_ms = actual_ms
        job.completed_at = now

        # Update circuit stats
        if circuit:
            circuit.proofs_generated = (circuit.proofs_generated or 0) + 1

        await db.commit()

        logger.info("Proof job %d completed: proof_hash=%s time=%dms", job_id, proof_hash, actual_ms)
        return {"job_id": job_id, "proof_id": proof.id, "status": "completed"}
