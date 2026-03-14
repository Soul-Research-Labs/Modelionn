"""Audit trail query routes — read-only access to audit logs."""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.database import AuditLogRow, MembershipRow


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

# Characters that trigger formula execution in spreadsheet applications
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: str | None) -> str | None:
    """Prevent CSV formula injection by prefixing dangerous cells with a tab."""
    if value is None:
        return None
    if value and value[0] in _CSV_DANGEROUS_PREFIXES:
        return f"\t{value}"
    return value


async def _caller_org_ids(db: AsyncSession, hotkey: str) -> list[int]:
    """Return org IDs the caller belongs to (any role)."""
    rows = (await db.execute(
        select(MembershipRow.org_id)
        .join(MembershipRow.user)
        .where(MembershipRow.user.has(hotkey=hotkey))
    )).scalars().all()
    return list(rows)


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    action: str | None = Query(None, description="Filter by action type"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    actor_hotkey: str | None = Query(None, description="Filter by actor hotkey"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> AuditLogList:
    # Scope to caller's orgs — only logs with a matching org_id (or NULL org_id
    # produced by the caller themselves) are visible.
    org_ids = await _caller_org_ids(db, publisher)
    if org_ids:
        base = select(AuditLogRow).where(AuditLogRow.org_id.in_(org_ids))
    else:
        # User not in any org: only see their own actions with no org context
        base = select(AuditLogRow).where(
            AuditLogRow.actor_hotkey == publisher,
            AuditLogRow.org_id.is_(None),
        )
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
    from_date: date | None = Query(None, description="Start date (inclusive) YYYY-MM-DD"),
    to_date: date | None = Query(None, description="End date (inclusive) YYYY-MM-DD"),
    limit: int = Query(10_000, ge=1, le=100_000),
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> StreamingResponse:
    """Export audit logs as a downloadable CSV file (streamed row-by-row).

    Requires authentication. Date range filtering is strongly recommended
    to avoid exporting extremely large result sets.
    """
    query = select(AuditLogRow).order_by(AuditLogRow.created_at.desc())
    # Scope to caller's orgs
    org_ids = await _caller_org_ids(db, publisher)
    if org_ids:
        query = query.where(AuditLogRow.org_id.in_(org_ids))
    else:
        query = query.where(
            AuditLogRow.actor_hotkey == publisher,
            AuditLogRow.org_id.is_(None),
        )
    if action:
        query = query.where(AuditLogRow.action == action)
    if resource_type:
        query = query.where(AuditLogRow.resource_type == resource_type)
    if actor_hotkey:
        query = query.where(AuditLogRow.actor_hotkey == actor_hotkey)
    if from_date:
        query = query.where(AuditLogRow.created_at >= from_date.isoformat())
    if to_date:
        query = query.where(AuditLogRow.created_at < (to_date.isoformat() + "T23:59:59.999999"))
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
                r.resource_id,
                _sanitize_csv_cell(r.old_value),
                _sanitize_csv_cell(r.new_value),
                r.ip_address,
                r.created_at.isoformat(),
            ])
            yield buf.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
