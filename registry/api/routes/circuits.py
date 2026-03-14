"""Circuit routes — upload, list, get, and search ZK circuits."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.config import settings
from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.database import CircuitRow, ProofType, CircuitCategory

logger = logging.getLogger(__name__)
router = APIRouter()

# IPFS CID v0 (Qm...) or v1 (ba...)
_CID_RE = re.compile(r'^Qm[1-9A-HJ-NP-Za-km-z]{44}$|^b[a-z2-7]{58}$')


# ── Request / Response Models ────────────────────────────────

class CircuitUploadRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    version: str = Field("1.0.0", max_length=64)
    description: str = Field("", max_length=4096)
    proof_type: str = Field(..., description="groth16|plonk|halo2|stark")
    circuit_type: str = Field("general", description="general|evm|zkml|custom")
    num_constraints: int = Field(..., gt=0)
    num_public_inputs: int = Field(0, ge=0)
    num_private_inputs: int = Field(0, ge=0)
    ipfs_cid: str = Field(..., min_length=1, max_length=128)
    proving_key_cid: str | None = None
    verification_key_cid: str | None = None
    size_bytes: int = Field(0, ge=0)
    tags: list[str] = Field(default_factory=list)
    config: dict | None = None


class CircuitResponse(BaseModel):
    id: int
    circuit_hash: str
    name: str
    version: str
    description: str
    proof_type: str
    circuit_type: str
    num_constraints: int
    num_public_inputs: int
    num_private_inputs: int
    ipfs_cid: str
    proving_key_cid: str | None
    verification_key_cid: str | None
    size_bytes: int
    publisher_hotkey: str
    downloads: int
    proofs_generated: int
    tags: list[str]
    created_at: str
    updated_at: str


class CircuitList(BaseModel):
    items: list[CircuitResponse]
    total: int
    page: int
    page_size: int


def _circuit_to_response(row: CircuitRow) -> dict:
    return {
        "id": row.id,
        "circuit_hash": row.circuit_hash,
        "name": row.name,
        "version": row.version,
        "description": row.description,
        "proof_type": row.proof_type if isinstance(row.proof_type, str) else row.proof_type.value,
        "circuit_type": row.circuit_type if isinstance(row.circuit_type, str) else row.circuit_type.value,
        "num_constraints": row.num_constraints,
        "num_public_inputs": row.num_public_inputs,
        "num_private_inputs": row.num_private_inputs,
        "ipfs_cid": row.ipfs_cid,
        "proving_key_cid": row.proving_key_cid,
        "verification_key_cid": row.verification_key_cid,
        "size_bytes": row.size_bytes,
        "publisher_hotkey": row.publisher_hotkey,
        "downloads": row.downloads,
        "proofs_generated": row.proofs_generated,
        "tags": [t.strip() for t in row.tags_csv.split(",") if t.strip()] if row.tags_csv else [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("", status_code=201, response_model=CircuitResponse)
async def upload_circuit(
    body: CircuitUploadRequest,
    db: AsyncSession = Depends(get_db),
    publisher_hotkey: str = Depends(verify_publisher),
) -> dict:
    """Upload a new ZK circuit to the registry."""
    # Validate proof type
    try:
        proof_type = ProofType(body.proof_type)
    except ValueError:
        raise HTTPException(400, f"Invalid proof_type: {body.proof_type}")

    try:
        circuit_type = CircuitCategory(body.circuit_type)
    except ValueError:
        raise HTTPException(400, f"Invalid circuit_type: {body.circuit_type}")

    if body.num_constraints > settings.max_circuit_constraints:
        raise HTTPException(400, f"Circuit exceeds max constraints ({settings.max_circuit_constraints})")

    # Per-publisher upload rate limit: max 50 circuits per publisher
    # Use FOR UPDATE to lock rows and prevent TOCTOU race on concurrent uploads
    publisher_circuit_count = (await db.execute(
        select(func.count()).select_from(
            select(CircuitRow.id)
            .where(CircuitRow.publisher_hotkey == publisher_hotkey)
            .with_for_update()
            .subquery()
        )
    )).scalar() or 0
    if publisher_circuit_count >= 50:
        raise HTTPException(429, "Upload limit reached (max 50 circuits per publisher)")

    # Validate IPFS CID format
    if not _CID_RE.match(body.ipfs_cid):
        raise HTTPException(400, f"Invalid IPFS CID format: {body.ipfs_cid[:40]}")
    if body.proving_key_cid and not _CID_RE.match(body.proving_key_cid):
        raise HTTPException(400, "Invalid proving_key_cid format")
    if body.verification_key_cid and not _CID_RE.match(body.verification_key_cid):
        raise HTTPException(400, "Invalid verification_key_cid format")

    # Compute circuit hash
    hash_input = f"{body.name}:{body.version}:{body.ipfs_cid}:{body.num_constraints}"
    circuit_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    # Check duplicate
    existing = await db.execute(
        select(CircuitRow).where(CircuitRow.circuit_hash == circuit_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Circuit with this hash already exists")

    # Check name+version unique
    existing_nv = await db.execute(
        select(CircuitRow).where(CircuitRow.name == body.name, CircuitRow.version == body.version)
    )
    if existing_nv.scalar_one_or_none():
        raise HTTPException(409, f"Circuit {body.name}@{body.version} already exists")

    row = CircuitRow(
        circuit_hash=circuit_hash,
        name=body.name,
        version=body.version,
        description=body.description,
        proof_type=proof_type,
        circuit_type=circuit_type,
        num_constraints=body.num_constraints,
        num_public_inputs=body.num_public_inputs,
        num_private_inputs=body.num_private_inputs,
        ipfs_cid=body.ipfs_cid,
        proving_key_cid=body.proving_key_cid,
        verification_key_cid=body.verification_key_cid,
        size_bytes=body.size_bytes,
        publisher_hotkey=publisher_hotkey,
        tags_csv=",".join(body.tags) if body.tags else "",
        config_json=json.dumps(body.config) if body.config else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Circuit uploaded: %s@%s hash=%s", body.name, body.version, circuit_hash)
    return _circuit_to_response(row)


@router.get("", response_model=CircuitList)
async def list_circuits(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    proof_type: str | None = None,
    circuit_type: str | None = None,
    search: str | None = None,
) -> dict:
    """List circuits with optional filters."""
    query = select(CircuitRow).where(CircuitRow.deleted_at.is_(None))
    count_query = select(func.count()).select_from(CircuitRow).where(CircuitRow.deleted_at.is_(None))

    if proof_type:
        query = query.where(CircuitRow.proof_type == proof_type)
        count_query = count_query.where(CircuitRow.proof_type == proof_type)
    if circuit_type:
        query = query.where(CircuitRow.circuit_type == circuit_type)
        count_query = count_query.where(CircuitRow.circuit_type == circuit_type)
    if search:
        pattern = f"%{search}%"
        query = query.where(CircuitRow.name.ilike(pattern) | CircuitRow.description.ilike(pattern))
        count_query = count_query.where(CircuitRow.name.ilike(pattern) | CircuitRow.description.ilike(pattern))

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(CircuitRow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [_circuit_to_response(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{circuit_id}", response_model=CircuitResponse)
async def get_circuit(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get circuit details by ID."""
    row = (await db.execute(select(CircuitRow).where(CircuitRow.id == circuit_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Circuit not found")
    return _circuit_to_response(row)


@router.get("/hash/{circuit_hash}", response_model=CircuitResponse)
async def get_circuit_by_hash(
    circuit_hash: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get circuit by content hash."""
    row = (await db.execute(select(CircuitRow).where(CircuitRow.circuit_hash == circuit_hash))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Circuit not found")
    return _circuit_to_response(row)


@router.post("/{circuit_id}/download")
async def track_download(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Increment download counter for a circuit."""
    result = await db.execute(
        update(CircuitRow)
        .where(CircuitRow.id == circuit_id)
        .values(downloads=CircuitRow.downloads + 1)
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Circuit not found")
    await db.commit()
    return {"status": "ok"}
