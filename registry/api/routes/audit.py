"""Audit trail query routes — read-only access to audit logs."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from registry.core.deps import get_db
from registry.models.database import AuditLogRow


class AuditLogResponse(BaseModel):
    id: int
    org_id: int | None = None
    actor_hotkey: str
    action: str
    resource_type: str
    resource_id: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    ip_address: str | None = None
    created_at: str


class AuditLogList(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int

router = APIRouter()


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    action: str | None = Query(None, description="Filter by action type"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    actor_hotkey: str | None = Query(None, description="Filter by actor hotkey"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AuditLogList:
    base = select(AuditLogRow)
    if action:
        base = base.where(AuditLogRow.action == action)
    if resource_type:
        base = base.where(AuditLogRow.resource_type == resource_type)
    if actor_hotkey:
        base = base.where(AuditLogRow.actor_hotkey == actor_hotkey)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    query = base.order_by(AuditLogRow.created_at.desc()).limit(page_size).offset(offset)
    result = await db.execute(query)
    rows = result.scalars().all()

    items = [
        AuditLogResponse(
            id=r.id,
            org_id=r.org_id,
            actor_hotkey=r.actor_hotkey,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            old_value=r.old_value,
            new_value=r.new_value,
            ip_address=r.ip_address,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return AuditLogList(items=items, total=total, page=page, page_size=page_size)


@router.get("/export")
async def export_audit_csv(
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    actor_hotkey: str | None = Query(None),
    limit: int = Query(10_000, ge=1, le=100_000),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit logs as a downloadable CSV file (streamed row-by-row)."""
    query = select(AuditLogRow).order_by(AuditLogRow.created_at.desc())
    if action:
        query = query.where(AuditLogRow.action == action)
    if resource_type:
        query = query.where(AuditLogRow.resource_type == resource_type)
    if actor_hotkey:
        query = query.where(AuditLogRow.actor_hotkey == actor_hotkey)
    query = query.limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    async def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "org_id", "actor_hotkey", "action", "resource_type",
                          "resource_id", "old_value", "new_value", "ip_address", "created_at"])
        yield buf.getvalue()
        for r in rows:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                r.id, r.org_id, r.actor_hotkey, r.action, r.resource_type,
                r.resource_id, r.old_value, r.new_value, r.ip_address,
                r.created_at.isoformat(),
            ])
            yield buf.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
