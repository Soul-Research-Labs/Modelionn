"""Prover routes — list, register, and manage prover (miner) nodes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.config import settings
from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.audit import log_audit
from registry.models.database import ProverCapabilityRow, GpuBackendEnum, AuditAction

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response Models ────────────────────────────────

# Upper bounds for prover capability claims (prevent spoofing)
_MAX_VRAM_BYTES = 2 * 1024**4          # 2 TB (well beyond any current GPU)
_MAX_COMPUTE_UNITS = 1_000_000         # Reasonable ceiling
_MAX_BENCHMARK_SCORE = 100_000.0       # Normalized score ceiling
_MAX_CONSTRAINTS = 10_000_000_000      # 10B constraints
_VALID_PROOF_TYPES = frozenset({"groth16", "plonk", "halo2", "stark"})


class ProverRegisterRequest(BaseModel):
    gpu_name: str = Field("", max_length=256)
    gpu_backend: str = Field("cpu", description="cuda|rocm|metal|webgpu|cpu")
    gpu_count: int = Field(1, ge=1, le=64)
    vram_total_bytes: int = Field(0, ge=0, le=_MAX_VRAM_BYTES)
    vram_available_bytes: int = Field(0, ge=0, le=_MAX_VRAM_BYTES)
    compute_units: int = Field(0, ge=0, le=_MAX_COMPUTE_UNITS)
    compute_version: str = Field("", max_length=32)
    benchmark_score: float = Field(0.0, ge=0.0, le=_MAX_BENCHMARK_SCORE)
    supported_proof_types: list[str] = Field(default_factory=lambda: ["groth16", "plonk", "halo2", "stark"])
    max_constraints: int = Field(0, ge=0, le=_MAX_CONSTRAINTS)


class ProverResponse(BaseModel):
    id: int
    hotkey: str
    gpu_name: str
    gpu_backend: str
    gpu_count: int
    vram_total_bytes: int
    vram_available_bytes: int
    compute_units: int
    benchmark_score: float
    supported_proof_types: list[str]
    max_constraints: int
    total_proofs: int
    successful_proofs: int
    failed_proofs: int
    avg_proof_time_ms: float
    uptime_ratio: float
    online: bool
    stake: float
    last_ping_at: str | None
    created_at: str


class ProverList(BaseModel):
    items: list[ProverResponse]
    total: int
    page: int
    page_size: int


class NetworkStats(BaseModel):
    total_provers: int
    online_provers: int
    total_gpus: int
    total_vram_bytes: int
    total_proofs_generated: int
    avg_proof_time_ms: float
    proof_systems: dict[str, int]
    gpu_backends: dict[str, int]


def _prover_to_response(row: ProverCapabilityRow) -> dict:
    gpu_backend_val = row.gpu_backend if isinstance(row.gpu_backend, str) else row.gpu_backend.value
    return {
        "id": row.id,
        "hotkey": row.hotkey,
        "gpu_name": row.gpu_name,
        "gpu_backend": gpu_backend_val,
        "gpu_count": row.gpu_count,
        "vram_total_bytes": row.vram_total_bytes,
        "vram_available_bytes": row.vram_available_bytes,
        "compute_units": row.compute_units,
        "benchmark_score": row.benchmark_score,
        "supported_proof_types": [s.strip() for s in row.supported_proof_types_csv.split(",") if s.strip()],
        "max_constraints": row.max_constraints,
        "total_proofs": row.total_proofs,
        "successful_proofs": row.successful_proofs,
        "failed_proofs": row.failed_proofs,
        "avg_proof_time_ms": row.avg_proof_time_ms,
        "uptime_ratio": row.uptime_ratio,
        "online": row.online,
        "stake": row.stake,
        "last_ping_at": row.last_ping_at.isoformat() if row.last_ping_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/register", status_code=201, response_model=ProverResponse)
async def register_prover(
    body: ProverRegisterRequest,
    db: AsyncSession = Depends(get_db),
    hotkey: str = Depends(verify_publisher),
) -> dict:
    """Register or update a prover node's capabilities."""
    try:
        gpu_backend = GpuBackendEnum(body.gpu_backend)
    except ValueError:
        raise HTTPException(400, f"Invalid gpu_backend: {body.gpu_backend}")

    # Validate proof type claims
    invalid_types = set(body.supported_proof_types) - _VALID_PROOF_TYPES
    if invalid_types:
        raise HTTPException(400, f"Invalid proof types: {', '.join(sorted(invalid_types))}")

    # vram_available cannot exceed vram_total
    if body.vram_available_bytes > body.vram_total_bytes:
        raise HTTPException(400, "vram_available_bytes cannot exceed vram_total_bytes")

    # Upsert: update if exists, create if not
    existing = (await db.execute(
        select(ProverCapabilityRow).where(ProverCapabilityRow.hotkey == hotkey)
    )).scalar_one_or_none()

    if existing:
        existing.gpu_name = body.gpu_name
        existing.gpu_backend = gpu_backend
        existing.gpu_count = body.gpu_count
        existing.vram_total_bytes = body.vram_total_bytes
        existing.vram_available_bytes = body.vram_available_bytes
        existing.compute_units = body.compute_units
        existing.compute_version = body.compute_version
        existing.benchmark_score = body.benchmark_score
        existing.supported_proof_types_csv = ",".join(body.supported_proof_types)
        existing.max_constraints = body.max_constraints
        existing.online = True
        existing.last_ping_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return _prover_to_response(existing)

    row = ProverCapabilityRow(
        hotkey=hotkey,
        gpu_name=body.gpu_name,
        gpu_backend=gpu_backend,
        gpu_count=body.gpu_count,
        vram_total_bytes=body.vram_total_bytes,
        vram_available_bytes=body.vram_available_bytes,
        compute_units=body.compute_units,
        compute_version=body.compute_version,
        benchmark_score=body.benchmark_score,
        supported_proof_types_csv=",".join(body.supported_proof_types),
        max_constraints=body.max_constraints,
        online=True,
        last_ping_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await log_audit(
        db,
        action=AuditAction.PROVER_REGISTERED,
        resource_type="prover",
        resource_id=hotkey,
        actor_hotkey=hotkey,
        new_value={"gpu_name": body.gpu_name, "gpu_backend": body.gpu_backend, "gpu_count": body.gpu_count},
    )
    await db.commit()
    logger.info("Prover registered: %s gpu=%s", hotkey, body.gpu_name)
    return _prover_to_response(row)


@router.post("/ping")
async def prover_ping(
    db: AsyncSession = Depends(get_db),
    hotkey: str = Depends(verify_publisher),
    vram_available_bytes: int = Query(0, ge=0),
) -> dict:
    """Heartbeat ping from a prover node."""
    result = await db.execute(
        update(ProverCapabilityRow)
        .where(ProverCapabilityRow.hotkey == hotkey)
        .values(
            online=True,
            last_ping_at=datetime.now(timezone.utc),
            vram_available_bytes=vram_available_bytes,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Prover not registered")
    await db.commit()
    return {"status": "ok"}


@router.get("", response_model=ProverList)
async def list_provers(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    online_only: bool = False,
    gpu_backend: str | None = None,
    proof_type: str | None = None,
    sort_by: str = Query("benchmark_score", description="benchmark_score|total_proofs|uptime_ratio"),
) -> dict:
    """List prover nodes."""
    query = select(ProverCapabilityRow)
    count_query = select(func.count()).select_from(ProverCapabilityRow)

    if online_only:
        query = query.where(ProverCapabilityRow.online == True)
        count_query = count_query.where(ProverCapabilityRow.online == True)
    if gpu_backend:
        query = query.where(ProverCapabilityRow.gpu_backend == gpu_backend)
        count_query = count_query.where(ProverCapabilityRow.gpu_backend == gpu_backend)
    if proof_type:
        query = query.where(ProverCapabilityRow.supported_proof_types_csv.contains(proof_type))
        count_query = count_query.where(ProverCapabilityRow.supported_proof_types_csv.contains(proof_type))

    # Sort
    sort_col = {
        "benchmark_score": ProverCapabilityRow.benchmark_score.desc(),
        "total_proofs": ProverCapabilityRow.total_proofs.desc(),
        "uptime_ratio": ProverCapabilityRow.uptime_ratio.desc(),
    }.get(sort_by, ProverCapabilityRow.benchmark_score.desc())
    query = query.order_by(sort_col)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [_prover_to_response(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats", response_model=NetworkStats)
async def network_stats(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get network-wide prover statistics."""
    total = (await db.execute(select(func.count()).select_from(ProverCapabilityRow))).scalar() or 0
    online = (await db.execute(
        select(func.count()).select_from(ProverCapabilityRow).where(ProverCapabilityRow.online == True)
    )).scalar() or 0
    total_gpus = (await db.execute(
        select(func.sum(ProverCapabilityRow.gpu_count))
    )).scalar() or 0
    total_vram = (await db.execute(
        select(func.sum(ProverCapabilityRow.vram_total_bytes))
    )).scalar() or 0
    total_proofs_sum = (await db.execute(
        select(func.sum(ProverCapabilityRow.total_proofs))
    )).scalar() or 0
    avg_time = (await db.execute(
        select(func.avg(ProverCapabilityRow.avg_proof_time_ms)).where(ProverCapabilityRow.total_proofs > 0)
    )).scalar() or 0.0

    # GPU backend distribution
    gpu_rows = (await db.execute(
        select(ProverCapabilityRow.gpu_backend, func.count()).group_by(ProverCapabilityRow.gpu_backend)
    )).all()
    gpu_backends = {str(r[0].value if hasattr(r[0], 'value') else r[0]): r[1] for r in gpu_rows}

    # Proof system distribution — aggregate from comma-separated proof types
    csv_rows = (await db.execute(
        select(ProverCapabilityRow.supported_proof_types_csv).where(
            ProverCapabilityRow.supported_proof_types_csv.isnot(None),
            ProverCapabilityRow.supported_proof_types_csv != "",
        )
    )).scalars().all()
    proof_systems: dict[str, int] = {}
    for csv in csv_rows:
        for pt in csv.split(","):
            pt = pt.strip()
            if pt:
                proof_systems[pt] = proof_systems.get(pt, 0) + 1

    return {
        "total_provers": total,
        "online_provers": online,
        "total_gpus": total_gpus,
        "total_vram_bytes": total_vram,
        "total_proofs_generated": total_proofs_sum,
        "avg_proof_time_ms": float(avg_time),
        "proof_systems": proof_systems,
        "gpu_backends": gpu_backends,
    }


@router.get("/{hotkey_param}", response_model=ProverResponse)
async def get_prover(
    hotkey_param: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get prover details by hotkey."""
    row = (await db.execute(
        select(ProverCapabilityRow).where(ProverCapabilityRow.hotkey == hotkey_param)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Prover not found")
    return _prover_to_response(row)


@router.get("/{hotkey_param}/reputation")
async def get_prover_reputation(
    hotkey_param: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get prover reputation score and performance metrics history."""
    from registry.models.database import ProofJobRow, CircuitPartitionRow

    row = (await db.execute(
        select(ProverCapabilityRow).where(ProverCapabilityRow.hotkey == hotkey_param)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Prover not found")

    # Count partition assignments and completions
    total_assigned = (await db.execute(
        select(func.count()).select_from(CircuitPartitionRow).where(
            CircuitPartitionRow.assigned_prover == hotkey_param,
        )
    )).scalar() or 0

    total_completed = (await db.execute(
        select(func.count()).select_from(CircuitPartitionRow).where(
            CircuitPartitionRow.assigned_prover == hotkey_param,
            CircuitPartitionRow.status == "completed",
        )
    )).scalar() or 0

    total_failed = (await db.execute(
        select(func.count()).select_from(CircuitPartitionRow).where(
            CircuitPartitionRow.assigned_prover == hotkey_param,
            CircuitPartitionRow.status == "failed",
        )
    )).scalar() or 0

    avg_gen_time = (await db.execute(
        select(func.avg(CircuitPartitionRow.generation_time_ms)).where(
            CircuitPartitionRow.assigned_prover == hotkey_param,
            CircuitPartitionRow.status == "completed",
            CircuitPartitionRow.generation_time_ms.isnot(None),
        )
    )).scalar() or 0.0

    completion_rate = total_completed / max(total_assigned, 1)
    # Reputation score: weighted combination of completion rate, uptime, and benchmark
    reputation_score = (
        0.4 * completion_rate
        + 0.3 * float(row.uptime_ratio or 0.0)
        + 0.3 * min(float(row.benchmark_score or 0.0) / 100.0, 1.0)
    )

    return {
        "hotkey": hotkey_param,
        "reputation_score": round(reputation_score, 4),
        "completion_rate": round(completion_rate, 4),
        "total_assigned": total_assigned,
        "total_completed": total_completed,
        "total_failed": total_failed,
        "avg_generation_time_ms": round(float(avg_gen_time), 2),
        "benchmark_score": float(row.benchmark_score or 0.0),
        "uptime_ratio": float(row.uptime_ratio or 0.0),
        "online": row.online,
        "stake": float(row.stake or 0.0),
    }
