"""Proof routes — request, poll, verify, and list ZK proofs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.config import settings
from registry.core.deps import get_db
from registry.models.database import (
    CircuitRow,
    ProofJobRow,
    ProofJobStatus,
    ProofRow,
    ProofType,
    CircuitPartitionRow,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_CID_RE = re.compile(r'^Qm[1-9A-HJ-NP-Za-km-z]{44}$|^b[a-z2-7]{58}$')


# ── Request / Response Models ────────────────────────────────

class ProofRequest(BaseModel):
    circuit_id: int = Field(..., gt=0)
    witness_cid: str = Field(..., min_length=1, max_length=128)
    public_inputs: dict | None = None
    gpu_preference: str | None = None
    config: dict | None = None


class ProofJobResponse(BaseModel):
    id: int
    task_id: str
    circuit_id: int
    circuit_name: str | None = None
    requester_hotkey: str
    status: str
    num_partitions: int
    partitions_completed: int
    redundancy: int
    estimated_time_ms: int | None
    actual_time_ms: int | None
    result_proof_id: int | None
    error: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class ProofResponse(BaseModel):
    id: int
    proof_hash: str
    circuit_id: int
    proof_type: str
    proof_data_cid: str
    public_inputs: dict | None
    proof_size_bytes: int
    generation_time_ms: int
    gpu_backend: str | None
    prover_hotkey: str
    verified: bool
    verified_by: str | None
    created_at: str


class VerifyRequest(BaseModel):
    proof_id: int = Field(..., gt=0)
    public_inputs: dict | None = None


class VerifyResponse(BaseModel):
    valid: bool
    proof_id: int
    circuit_id: int
    proof_system: str
    details: str


class ProofJobList(BaseModel):
    items: list[ProofJobResponse]
    total: int
    page: int
    page_size: int


class ProofList(BaseModel):
    items: list[ProofResponse]
    total: int
    page: int
    page_size: int


class PartitionStatus(BaseModel):
    partition_index: int
    status: str
    assigned_prover: str | None
    generation_time_ms: int | None
    gpu_backend_used: str | None


def _job_to_response(row: ProofJobRow) -> dict:
    circuit_name = row.circuit.name if row.circuit else None
    return {
        "id": row.id,
        "task_id": row.task_id,
        "circuit_id": row.circuit_id,
        "circuit_name": circuit_name,
        "requester_hotkey": row.requester_hotkey,
        "status": row.status if isinstance(row.status, str) else row.status.value,
        "num_partitions": row.num_partitions,
        "partitions_completed": row.partitions_completed,
        "redundancy": row.redundancy,
        "estimated_time_ms": row.estimated_time_ms,
        "actual_time_ms": row.actual_time_ms,
        "result_proof_id": row.result_proof_id,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _proof_to_response(row: ProofRow) -> dict:
    return {
        "id": row.id,
        "proof_hash": row.proof_hash,
        "circuit_id": row.circuit_id,
        "proof_type": row.proof_type if isinstance(row.proof_type, str) else row.proof_type.value,
        "proof_data_cid": row.proof_data_cid,
        "public_inputs": json.loads(row.public_inputs_json) if row.public_inputs_json else None,
        "proof_size_bytes": row.proof_size_bytes,
        "generation_time_ms": row.generation_time_ms,
        "gpu_backend": row.gpu_backend if isinstance(row.gpu_backend, str) else (row.gpu_backend.value if row.gpu_backend else None),
        "prover_hotkey": row.prover_hotkey,
        "verified": row.verified,
        "verified_by": row.verified_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/jobs", status_code=202, response_model=ProofJobResponse)
async def request_proof(
    body: ProofRequest,
    db: AsyncSession = Depends(get_db),
    requester_hotkey: str = Query(..., alias="hotkey", min_length=1, max_length=128),
) -> dict:
    """Submit a proof generation request."""
    # Verify circuit exists
    circuit = (await db.execute(
        select(CircuitRow).where(CircuitRow.id == body.circuit_id)
    )).scalar_one_or_none()
    if not circuit:
        raise HTTPException(404, "Circuit not found")

    # Validate witness CID format
    if not _CID_RE.match(body.witness_cid):
        raise HTTPException(400, f"Invalid witness CID format: {body.witness_cid[:40]}")

    # Rate limit: max 10 pending jobs per user
    pending_count = (await db.execute(
        select(func.count()).select_from(ProofJobRow).where(
            ProofJobRow.requester_hotkey == requester_hotkey,
            ProofJobRow.status.in_([ProofJobStatus.QUEUED.value, ProofJobStatus.DISPATCHED.value, ProofJobStatus.PROVING.value]),
        )
    )).scalar() or 0
    if pending_count >= 10:
        raise HTTPException(429, "Too many pending proof jobs (max 10)")

    task_id = uuid.uuid4().hex[:16]

    # Estimate partitions
    max_per = settings.max_constraints_per_partition
    num_partitions = max(1, (circuit.num_constraints + max_per - 1) // max_per)
    num_partitions = min(num_partitions, settings.max_partitions_per_job)

    row = ProofJobRow(
        task_id=task_id,
        circuit_id=body.circuit_id,
        requester_hotkey=requester_hotkey,
        status=ProofJobStatus.QUEUED,
        num_partitions=num_partitions,
        redundancy=settings.partition_redundancy,
        witness_cid=body.witness_cid,
        public_inputs_json=json.dumps(body.public_inputs) if body.public_inputs else None,
        config_json=json.dumps(body.config) if body.config else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Dispatch to Celery
    try:
        from registry.tasks.proof_dispatch import dispatch_proof_job
        dispatch_proof_job.delay(row.id)
    except Exception as exc:
        logger.warning("Celery unavailable for proof dispatch: %s", exc)

    logger.info("Proof job created: task_id=%s circuit=%s partitions=%d", task_id, circuit.name, num_partitions)
    return _job_to_response(row)


@router.get("/jobs/{task_id}", response_model=ProofJobResponse)
async def get_proof_job(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get proof job status."""
    row = (await db.execute(
        select(ProofJobRow).where(ProofJobRow.task_id == task_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Proof job not found")
    return _job_to_response(row)


@router.get("/jobs/{task_id}/partitions", response_model=list[PartitionStatus])
async def get_job_partitions(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get partition-level status for a proof job."""
    job = (await db.execute(
        select(ProofJobRow).where(ProofJobRow.task_id == task_id)
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Proof job not found")

    partitions = (await db.execute(
        select(CircuitPartitionRow)
        .where(CircuitPartitionRow.job_id == job.id)
        .order_by(CircuitPartitionRow.partition_index)
    )).scalars().all()

    return [
        {
            "partition_index": p.partition_index,
            "status": p.status,
            "assigned_prover": p.assigned_prover,
            "generation_time_ms": p.generation_time_ms,
            "gpu_backend_used": p.gpu_backend_used if isinstance(p.gpu_backend_used, str) else (p.gpu_backend_used.value if p.gpu_backend_used else None),
        }
        for p in partitions
    ]


@router.get("/jobs", response_model=ProofJobList)
async def list_proof_jobs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    requester: str | None = None,
) -> dict:
    """List proof jobs with filters."""
    query = select(ProofJobRow)
    count_query = select(func.count()).select_from(ProofJobRow)

    if status:
        query = query.where(ProofJobRow.status == status)
        count_query = count_query.where(ProofJobRow.status == status)
    if requester:
        query = query.where(ProofJobRow.requester_hotkey == requester)
        count_query = count_query.where(ProofJobRow.requester_hotkey == requester)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(ProofJobRow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [_job_to_response(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("", response_model=ProofList)
async def list_proofs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    circuit_id: int | None = None,
    verified: bool | None = None,
) -> dict:
    """List generated proofs."""
    query = select(ProofRow)
    count_query = select(func.count()).select_from(ProofRow)

    if circuit_id:
        query = query.where(ProofRow.circuit_id == circuit_id)
        count_query = count_query.where(ProofRow.circuit_id == circuit_id)
    if verified is not None:
        query = query.where(ProofRow.verified == verified)
        count_query = count_query.where(ProofRow.verified == verified)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(ProofRow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [_proof_to_response(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{proof_id}", response_model=ProofResponse)
async def get_proof(
    proof_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get proof details."""
    row = (await db.execute(select(ProofRow).where(ProofRow.id == proof_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Proof not found")
    return _proof_to_response(row)


@router.post("/verify", response_model=VerifyResponse)
async def verify_proof(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a generated proof using the Rust prover engine."""
    proof = (await db.execute(select(ProofRow).where(ProofRow.id == body.proof_id))).scalar_one_or_none()
    if not proof:
        raise HTTPException(404, "Proof not found")

    circuit = (await db.execute(select(CircuitRow).where(CircuitRow.id == proof.circuit_id))).scalar_one_or_none()
    if not circuit:
        raise HTTPException(404, "Circuit not found")

    proof_type_val = proof.proof_type if isinstance(proof.proof_type, str) else proof.proof_type.value

    # If already verified, return cached result
    if proof.verified:
        return {
            "valid": True,
            "proof_id": proof.id,
            "circuit_id": circuit.id,
            "proof_system": proof_type_val,
            "details": "Previously verified",
        }

    # Attempt real verification via Rust prover engine
    valid = False
    details = "Verification pending"
    try:
        from prover.python.modelionn_prover import (
            ProverEngine, CircuitData, ProofResult, ProofSystem, CircuitType,
        )
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage()

        # Download proof data and verification key from IPFS
        proof_bytes = await storage.download_bytes(proof.proof_data_cid)
        vk_bytes = b""
        if circuit.verification_key_cid:
            vk_bytes = await storage.download_bytes(circuit.verification_key_cid)

        ps_map = {
            "groth16": ProofSystem.GROTH16, "plonk": ProofSystem.PLONK,
            "halo2": ProofSystem.HALO2, "stark": ProofSystem.STARK,
        }
        ps = ps_map.get(proof_type_val, ProofSystem.GROTH16)

        circuit_data = CircuitData(
            id=str(circuit.id), name=circuit.name, proof_system=ps,
            circuit_type=CircuitType.GENERAL, num_constraints=circuit.num_constraints,
            num_public_inputs=0, num_private_inputs=0,
            data=b"", proving_key=b"", verification_key=vk_bytes,
        )

        public_inputs = b""
        if body.public_inputs:
            public_inputs = json.dumps(body.public_inputs).encode()
        elif proof.public_inputs_json:
            public_inputs = proof.public_inputs_json.encode()

        proof_result = ProofResult(
            proof_system=ps, data=proof_bytes,
            public_inputs=public_inputs,
            generation_time_ms=0, proof_size_bytes=len(proof_bytes),
        )

        engine = ProverEngine()
        valid = await engine.verify(circuit_data, proof_result)
        details = "Verification passed" if valid else "Verification failed"

        # Persist verification result
        proof.verified = valid
        proof.verified_by = "registry_api"
        await db.commit()

    except ImportError:
        details = "Rust prover engine unavailable — verification deferred to validator network"
    except Exception as exc:
        logger.error("Proof verification error for proof %d: %s", proof.id, exc)
        details = f"Verification error: {str(exc)[:200]}"

    return {
        "valid": valid,
        "proof_id": proof.id,
        "circuit_id": circuit.id,
        "proof_system": proof_type_val,
        "details": details,
    }
