"""Audit trail helpers — log all mutations for compliance and traceability.

Usage:
    await log_audit(db, action=AuditAction.CIRCUIT_UPLOADED,
                    resource_type="circuit", resource_id="42",
                    new_value={"name": "my-circuit"}, request=request)
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from registry.api.middleware.request_id import request_id_ctx
from registry.models.database import AuditAction, AuditLogRow


async def log_audit(
    db: AsyncSession,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: str,
    actor_hotkey: str = "",
    org_id: int | None = None,
    old_value: Any = None,
    new_value: Any = None,
    request: Request | None = None,
) -> AuditLogRow:
    """Append an immutable audit log entry."""
    ip = None
    if request and request.client:
        ip = request.client.host

    row = AuditLogRow(
        org_id=org_id,
        actor_hotkey=actor_hotkey,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=json.dumps(old_value) if old_value is not None else None,
        new_value=json.dumps(new_value) if new_value is not None else None,
        ip_address=ip,
    )
    db.add(row)
    # Don't commit here — let the caller's transaction handle it
    return row
