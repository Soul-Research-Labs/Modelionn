"""Proof aggregation Celery task — collects partition fragments and finalises jobs.

Lifecycle stages handled here:
    PROVING → AGGREGATING → VERIFYING → COMPLETED (or FAILED / TIMEOUT)

Runs periodically to sweep all jobs currently in PROVING status. For each:
1. Check whether every partition has been completed by a prover.
2. Download fragment CIDs from IPFS and concatenate into a single proof blob.
3. Upload the combined proof back to IPFS.
4. Verify the aggregated proof (calls the Rust prover engine).
5. Transition the job to COMPLETED with the final proof record.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone

from registry.tasks.celery_app import app

logger = logging.getLogger(__name__)

_CID_RE = re.compile(r'^Qm[1-9A-HJ-NP-Za-km-z]{44}$|^b[a-z2-7]{58}$')

# Maximum wall-clock seconds a job may spend in PROVING before it is timed out.
# Configurable per proof system via settings.prover_timeout_s.
def _get_max_proving_seconds() -> int:
    try:
        from registry.core.config import settings
        return settings.prover_timeout_s
    except Exception:
        return 1800  # 30 minute fallback


# Module-level constant for backward compat / tests
_MAX_PROVING_SECONDS: int = _get_max_proving_seconds()


def _reset_timeout_partitions(partitions: list) -> int:
    reset_count = 0
    for part in partitions:
        part.status = "pending"
        part.assigned_prover = None
        part.assigned_at = None
        part.error = "Reset after proving timeout"
        reset_count += 1
    return reset_count


@app.task(
    bind=True,
    name="registry.tasks.proof_aggregate.aggregate_completed_jobs",
    time_limit=300,
    max_retries=2,
    default_retry_delay=30,
)
def aggregate_completed_jobs(self) -> dict:
    """Periodic sweep: find PROVING jobs whose partitions are all done."""
    return asyncio.run(_aggregate_sweep(self))


async def _aggregate_sweep(task) -> dict:
    from sqlalchemy import select, func
    from registry.core.deps import async_session
    from registry.models.database import (
        ProofJobRow, ProofJobStatus, CircuitPartitionRow,
    )

    async with async_session() as db:
        # Fetch all jobs in PROVING state
        jobs = (
            await db.execute(
                select(ProofJobRow).where(
                    ProofJobRow.status == ProofJobStatus.PROVING
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        aggregated = 0
        timed_out = 0

        for job in jobs:
            # Skip jobs that were cancelled while proving
            if job.status == ProofJobStatus.CANCELLED:
                continue

            # Check for timeout
            max_proving_seconds = _get_max_proving_seconds()
            elapsed = (datetime.now(timezone.utc) - (job.started_at or job.created_at)).total_seconds()
            if elapsed > max_proving_seconds:
                reset_candidates = (
                    await db.execute(
                        select(CircuitPartitionRow)
                        .where(
                            CircuitPartitionRow.job_id == job.id,
                            CircuitPartitionRow.status.in_(["assigned", "proving"]),
                        )
                        .with_for_update()
                    )
                ).scalars().all()
                reset_count = _reset_timeout_partitions(reset_candidates)

                job.status = ProofJobStatus.TIMEOUT
                job.error = f"Proving timed out after {int(elapsed)}s (limit: {max_proving_seconds}s)"
                job.completed_at = datetime.now(timezone.utc)
                timed_out += 1
                logger.warning(
                    "Job %d timed out after %.0fs; reset %d partition(s) to pending",
                    job.id,
                    elapsed,
                    reset_count,
                )
                # Fire webhook for timeout
                try:
                    from registry.tasks.webhook_delivery import fire_webhooks_for_job
                    await fire_webhooks_for_job(job.id, "proof.timeout", {
                        "job_id": job.id, "task_id": job.task_id, "error": job.error,
                    })
                except Exception as exc:
                    logger.warning(
                        "Failed to queue timeout webhook for job %d: %s",
                        job.id,
                        exc,
                        exc_info=True,
                    )
                continue

            # Count partition statuses
            part_counts = dict(
                (
                    await db.execute(
                        select(
                            CircuitPartitionRow.status,
                            func.count(),
                        )
                        .where(CircuitPartitionRow.job_id == job.id)
                        .group_by(CircuitPartitionRow.status)
                    )
                ).all()
            )
            completed = part_counts.get("completed", 0)
            total = sum(part_counts.values())

            if total == 0:
                continue  # partitions not created yet

            if completed < job.num_partitions:
                # Check if remaining partitions all failed (no hope)
                failed = part_counts.get("failed", 0)
                pending_or_active = total - completed - failed
                if pending_or_active == 0 and completed < job.num_partitions:
                    job.status = ProofJobStatus.FAILED
                    job.error = f"Only {completed}/{job.num_partitions} partitions completed, rest failed"
                    job.completed_at = datetime.now(timezone.utc)
                    try:
                        from registry.tasks.webhook_delivery import fire_webhooks_for_job
                        await fire_webhooks_for_job(job.id, "proof.failed", {
                            "job_id": job.id, "task_id": job.task_id, "error": job.error,
                        })
                    except Exception as exc:
                        logger.warning(
                            "Failed to queue failure webhook for job %d: %s",
                            job.id,
                            exc,
                            exc_info=True,
                        )
                continue

            # All partitions completed — aggregate
            try:
                await _aggregate_job(db, job)
                aggregated += 1
            except Exception as exc:
                logger.error("Aggregation failed for job %d: %s", job.id, exc, exc_info=True)
                job.status = ProofJobStatus.FAILED
                job.error = f"Aggregation error: {str(exc)[:500]}"
                job.completed_at = datetime.now(timezone.utc)

        await db.commit()

    return {"aggregated": aggregated, "timed_out": timed_out, "checked": len(jobs)}


async def _aggregate_job(db, job) -> None:
    """Aggregate partition fragments into a single proof and verify."""
    from sqlalchemy import select
    from registry.models.database import (
        CircuitPartitionRow, CircuitRow, ProofRow,
        ProofJobStatus,
    )

    # 1. AGGREGATING — lock partitions to prevent concurrent modification
    job.status = ProofJobStatus.AGGREGATING
    await db.flush()

    partitions = (
        await db.execute(
            select(CircuitPartitionRow)
            .where(
                CircuitPartitionRow.job_id == job.id,
                CircuitPartitionRow.status == "completed",
            )
            .order_by(CircuitPartitionRow.partition_index)
            .with_for_update()
        )
    ).scalars().all()

    circuit = (
        await db.execute(
            select(CircuitRow).where(CircuitRow.id == job.circuit_id)
        )
    ).scalar_one_or_none()

    # Collect proof fragment CIDs from partitions
    fragment_cids = [p.proof_fragment_cid for p in partitions if p.proof_fragment_cid]

    if not fragment_cids:
        raise ValueError("No proof fragment CIDs found on completed partitions")

    # Validate CID format before downloading
    for cid in fragment_cids:
        if not _CID_RE.match(cid):
            raise ValueError(f"Invalid IPFS CID format in partition fragment: {cid[:40]}")

    # Download and concatenate fragments from IPFS
    from registry.storage.ipfs import IPFSStorage

    storage = IPFSStorage()
    fragments: list[bytes] = []
    for cid in fragment_cids:
        data = await storage.download_bytes(cid)
        fragments.append(data)

    # Pre-verify individual fragments before aggregation to avoid wasting
    # compute on combining invalid proofs.
    invalid_partitions: list[int] = []
    try:
        from prover.python.modelionn_prover import ProverEngine, CircuitData, ProofResult, ProofSystem, CircuitType

        ps_map = {"groth16": ProofSystem.GROTH16, "plonk": ProofSystem.PLONK,
                   "halo2": ProofSystem.HALO2, "stark": ProofSystem.STARK}
        proof_type_str = circuit.proof_type if isinstance(circuit.proof_type, str) else circuit.proof_type.value
        ps = ps_map.get(proof_type_str, ProofSystem.GROTH16)

        vk_bytes = b""
        if circuit.verification_key_cid:
            vk_bytes = await storage.download_bytes(circuit.verification_key_cid)

        engine = ProverEngine()
        for idx, frag_data in enumerate(fragments):
            try:
                cd = CircuitData(
                    id=str(circuit.id), name=circuit.name, proof_system=ps,
                    circuit_type=CircuitType.GENERAL, num_constraints=circuit.num_constraints,
                    num_public_inputs=0, num_private_inputs=0,
                    data=b"", proving_key=b"", verification_key=vk_bytes,
                )
                pr = ProofResult(
                    proof_system=ps, data=frag_data,
                    public_inputs=job.public_inputs_json.encode() if job.public_inputs_json else b"",
                    generation_time_ms=0, proof_size_bytes=len(frag_data),
                )
                if not await engine.verify(cd, pr):
                    invalid_partitions.append(idx)
                    logger.warning("Job %d partition %d: fragment verification failed", job.id, idx)
            except Exception as exc:
                invalid_partitions.append(idx)
                logger.warning("Job %d partition %d: fragment verification error: %s", job.id, idx, exc)
    except ImportError:
        logger.debug("Rust prover unavailable — skipping per-fragment pre-verification")

    if invalid_partitions:
        valid_ratio = (len(fragments) - len(invalid_partitions)) / len(fragments)
        if valid_ratio < 0.7:
            raise ValueError(
                f"Too many invalid fragments ({len(invalid_partitions)}/{len(fragments)}); "
                f"partitions {invalid_partitions}"
            )
        logger.warning(
            "Job %d: %d/%d fragments invalid but proceeding (%.0f%% valid)",
            job.id, len(invalid_partitions), len(fragments), valid_ratio * 100,
        )

    combined = b"".join(fragments)
    proof_hash = hashlib.sha256(combined).hexdigest()

    # Upload aggregated proof to IPFS
    upload_result = await storage.upload(combined, filename=f"proof_{job.task_id}.bin")
    proof_data_cid = upload_result.cid

    # 2. VERIFYING
    job.status = ProofJobStatus.VERIFYING
    await db.flush()

    verified = False
    try:
        from prover.python.modelionn_prover import ProverEngine, CircuitData, ProofResult, ProofSystem, CircuitType

        ps_map = {"groth16": ProofSystem.GROTH16, "plonk": ProofSystem.PLONK,
                   "halo2": ProofSystem.HALO2, "stark": ProofSystem.STARK}
        proof_type_str = circuit.proof_type if isinstance(circuit.proof_type, str) else circuit.proof_type.value
        ps = ps_map.get(proof_type_str, ProofSystem.GROTH16)

        # Download verification key
        vk_bytes = b""
        if circuit.verification_key_cid:
            vk_bytes = await storage.download_bytes(circuit.verification_key_cid)

        circuit_data = CircuitData(
            id=str(circuit.id), name=circuit.name, proof_system=ps,
            circuit_type=CircuitType.GENERAL, num_constraints=circuit.num_constraints,
            num_public_inputs=0, num_private_inputs=0,
            data=b"", proving_key=b"", verification_key=vk_bytes,
        )
        proof_result = ProofResult(
            proof_system=ps, data=combined,
            public_inputs=job.public_inputs_json.encode() if job.public_inputs_json else b"",
            generation_time_ms=0, proof_size_bytes=len(combined),
        )

        engine = ProverEngine()
        verified = await engine.verify(circuit_data, proof_result)
    except ImportError:
        from registry.core.config import settings as _settings
        if not _settings.debug:
            logger.error(
                "Rust prover unavailable in production for job %d — marking verification as failed",
                job.id,
            )
        else:
            logger.warning(
                "Rust prover unavailable in dev mode for job %d — proof will be marked unverified",
                job.id,
            )
        verified = False
    except Exception as exc:
        logger.error("Verification failed for job %d: %s", job.id, exc)
        # Still complete the job; verified=False is recorded

    # 3. COMPLETED — create proof record
    now = datetime.now(timezone.utc)
    actual_ms = int((now - (job.started_at or job.created_at)).total_seconds() * 1000)

    # Determine the prover that completed the most partitions
    primary_prover = max(
        (p.assigned_prover for p in partitions if p.assigned_prover),
        key=lambda h: sum(1 for p in partitions if p.assigned_prover == h),
        default=job.requester_hotkey,
    )

    proof = ProofRow(
        proof_hash=proof_hash,
        circuit_id=job.circuit_id,
        job_id=job.id,
        proof_type=circuit.proof_type if circuit else "groth16",
        proof_data_cid=proof_data_cid,
        public_inputs_json=job.public_inputs_json,
        proof_size_bytes=len(combined),
        generation_time_ms=actual_ms,
        prover_hotkey=primary_prover,
        verified=verified,
    )
    db.add(proof)
    await db.flush()

    job.status = ProofJobStatus.COMPLETED
    job.result_proof_id = proof.id
    job.actual_time_ms = actual_ms
    job.completed_at = now

    if circuit:
        circuit.proofs_generated = (circuit.proofs_generated or 0) + 1

    logger.info(
        "Job %d aggregated: proof_id=%d hash=%s verified=%s time=%dms fragments=%d",
        job.id, proof.id, proof_hash[:16], verified, actual_ms, len(fragments),
    )

    # Fire webhooks for job completion
    try:
        from registry.tasks.webhook_delivery import fire_webhooks_for_job
        await fire_webhooks_for_job(job.id, "proof.completed", {
            "job_id": job.id,
            "task_id": job.task_id,
            "proof_id": proof.id,
            "proof_hash": proof_hash,
            "verified": verified,
            "generation_time_ms": actual_ms,
        })
    except Exception as exc:
        logger.debug("Webhook delivery queueing failed (non-critical): %s", exc)
