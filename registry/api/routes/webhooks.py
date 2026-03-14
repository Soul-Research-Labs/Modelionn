"""Webhook configuration routes — create, list, update, delete."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.database import WebhookConfigRow

router = APIRouter()

MAX_WEBHOOKS_PER_USER = 10
VALID_EVENTS = {"*", "proof.completed", "proof.failed", "circuit.uploaded", "prover.online", "prover.offline"}


# ── Schemas ─────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    url: str = Field(..., max_length=2048)
    label: str = Field(default="", max_length=128)
    events: list[str] = Field(default=["*"])

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        for event in v:
            if event not in VALID_EVENTS:
                raise ValueError(f"Invalid event type: {event}")
        return v


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    label: str | None = Field(default=None, max_length=128)
    events: list[str] | None = None
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for event in v:
                if event not in VALID_EVENTS:
                    raise ValueError(f"Invalid event type: {event}")
        return v


class WebhookResponse(BaseModel):
    id: int
    url: str
    label: str
    events: list[str]
    active: bool
    created_at: str
    last_triggered_at: str | None

    model_config = {"from_attributes": True}


# ── Endpoints ───────────────────────────────────────────────

@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    caller: str = Depends(verify_publisher),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            select(WebhookConfigRow)
            .where(WebhookConfigRow.hotkey == caller)
            .order_by(WebhookConfigRow.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "url": r.url,
            "label": r.label,
            "events": r.events.split(",") if r.events else ["*"],
            "active": r.active,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
        }
        for r in rows
    ]


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreate,
    caller: str = Depends(verify_publisher),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Check limit
    count = (
        await db.execute(
            select(WebhookConfigRow.id).where(WebhookConfigRow.hotkey == caller)
        )
    ).scalars().all()
    if len(count) >= MAX_WEBHOOKS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_WEBHOOKS_PER_USER} webhooks per user",
        )

    secret = secrets.token_hex(32)
    row = WebhookConfigRow(
        hotkey=caller,
        url=body.url,
        label=body.label,
        events=",".join(body.events),
        secret=secret,
        active=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return {
        "id": row.id,
        "url": row.url,
        "label": row.label,
        "events": body.events,
        "active": row.active,
        "secret": secret,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "last_triggered_at": None,
    }


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: int,
    body: WebhookUpdate,
    caller: str = Depends(verify_publisher),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(WebhookConfigRow).where(
                WebhookConfigRow.id == webhook_id,
                WebhookConfigRow.hotkey == caller,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if body.url is not None:
        row.url = body.url
    if body.label is not None:
        row.label = body.label
    if body.events is not None:
        row.events = ",".join(body.events)
    if body.active is not None:
        row.active = body.active

    await db.commit()
    await db.refresh(row)

    return {
        "id": row.id,
        "url": row.url,
        "label": row.label,
        "events": row.events.split(",") if row.events else ["*"],
        "active": row.active,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None,
    }


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    caller: str = Depends(verify_publisher),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = (
        await db.execute(
            select(WebhookConfigRow).where(
                WebhookConfigRow.id == webhook_id,
                WebhookConfigRow.hotkey == caller,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(row)
    await db.commit()
