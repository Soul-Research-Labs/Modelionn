"""API key management routes — create, list, revoke."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.audit import log_audit
from registry.models.database import APIKeyRow, AuditAction

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    label: str = Field(default="", max_length=128)
    daily_limit: int = Field(default=1000, ge=1, le=100_000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365, description="Days until expiration (None = never)")


class APIKeyResponse(BaseModel):
    id: int
    label: str
    daily_limit: int
    requests_today: int
    expires_at: str | None = None
    created_at: str
    last_used_at: str | None = None


class APIKeyCreatedResponse(APIKeyResponse):
    key: str  # plaintext key — only returned on creation


# ── Endpoints ───────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=APIKeyCreatedResponse)
async def create_api_key(
    body: APIKeyCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> APIKeyCreatedResponse:
    """Generate a new API key for the authenticated publisher."""
    response.headers["Cache-Control"] = "no-store"
    raw_key = f"mnn_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at = None
    if body.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    row = APIKeyRow(
        key_hash=key_hash,
        hotkey=publisher,
        label=body.label,
        daily_limit=body.daily_limit,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await log_audit(
        db,
        action=AuditAction.API_KEY_CREATED,
        resource_type="api_key",
        resource_id=str(row.id),
        actor_hotkey=publisher,
        new_value={"label": body.label, "daily_limit": body.daily_limit},
    )
    await db.commit()

    return APIKeyCreatedResponse(
        id=row.id,
        label=row.label,
        daily_limit=row.daily_limit,
        requests_today=row.requests_today,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_at=row.created_at.isoformat(),
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        key=raw_key,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
    page: int = 1,
    page_size: int = 20,
) -> list[APIKeyResponse]:
    """List API keys for the authenticated publisher (paginated)."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size
    result = await db.execute(
        select(APIKeyRow)
        .where(APIKeyRow.hotkey == publisher)
        .order_by(APIKeyRow.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    return [
        APIKeyResponse(
            id=r.id,
            label=r.label,
            daily_limit=r.daily_limit,
            requests_today=r.requests_today,
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
            created_at=r.created_at.isoformat(),
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
        )
        for r in result.scalars().all()
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> None:
    """Revoke (delete) an API key."""
    result = await db.execute(
        select(APIKeyRow).where(APIKeyRow.id == key_id, APIKeyRow.hotkey == publisher)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    await log_audit(
        db,
        action=AuditAction.API_KEY_REVOKED,
        resource_type="api_key",
        resource_id=str(key_id),
        actor_hotkey=publisher,
        old_value={"label": row.label},
    )
    await db.execute(delete(APIKeyRow).where(APIKeyRow.id == key_id, APIKeyRow.hotkey == publisher))
    await db.commit()
