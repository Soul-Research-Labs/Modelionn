"""Organization management routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.core.deps import get_db
from registry.core.security import verify_publisher
from registry.models.audit import log_audit
from registry.models.database import (
    AuditAction,
    MembershipRow,
    OrgRole,
    OrganizationRow,
    UserRow,
)

router = APIRouter()

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){1,126}[a-z0-9]$")


# ── Schemas ─────────────────────────────────────────────────

class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=3, max_length=128)


class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    created_at: str


class MemberResponse(BaseModel):
    user_id: int
    hotkey: str
    role: str


# ── Endpoints ───────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrgResponse)
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> OrgResponse:
    if not _SLUG_RE.match(body.slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Slug must be 3-128 lowercase alphanumeric characters or hyphens",
        )

    existing = await db.execute(
        select(OrganizationRow).where(OrganizationRow.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Org slug '{body.slug}' already exists")

    # Atomic: create org + user + membership in one flush cycle
    user = await _ensure_user(db, publisher)

    org = OrganizationRow(name=body.name, slug=body.slug)
    db.add(org)
    await db.flush()  # assigns org.id

    membership = MembershipRow(user_id=user.id, org_id=org.id, role=OrgRole.ADMIN)
    db.add(membership)

    await log_audit(
        db,
        action=AuditAction.ORG_CREATED,
        resource_type="organization",
        resource_id=str(org.id),
        actor_hotkey=publisher,
        org_id=org.id,
        new_value={"name": body.name, "slug": body.slug},
    )

    await db.commit()
    await db.refresh(org)
    return OrgResponse(
        id=org.id, name=org.name, slug=org.slug,
        created_at=org.created_at.isoformat(),
    )


@router.get("/me", response_model=list[OrgResponse])
async def list_my_orgs(
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> list[OrgResponse]:
    """Return organizations the authenticated user belongs to."""
    user = await db.execute(select(UserRow).where(UserRow.hotkey == publisher))
    user_row = user.scalar_one_or_none()
    if not user_row:
        return []
    memberships = await db.execute(
        select(MembershipRow).where(MembershipRow.user_id == user_row.id)
    )
    return [
        OrgResponse(
            id=m.organization.id,
            name=m.organization.name,
            slug=m.organization.slug,
            created_at=m.organization.created_at.isoformat(),
        )
        for m in memberships.scalars().all()
    ]


@router.get("/{slug}", response_model=OrgResponse)
async def get_org(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> OrgResponse:
    result = await db.execute(
        select(OrganizationRow).where(OrganizationRow.slug == slug)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgResponse(
        id=org.id, name=org.name, slug=org.slug,
        created_at=org.created_at.isoformat(),
    )


@router.get("/{slug}/members")
async def list_members(
    slug: str,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    page = max(page, 1)
    page_size = min(page_size, 100)
    offset = (page - 1) * page_size
    org = await _get_org_by_slug(db, slug)
    base = (
        select(MembershipRow, UserRow)
        .join(UserRow, UserRow.id == MembershipRow.user_id)
        .where(MembershipRow.org_id == org.id)
    )
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0
    result = await db.execute(base.offset(offset).limit(page_size))
    members = [
        MemberResponse(user_id=user.id, hotkey=user.hotkey, role=membership.role)
        for membership, user in result
    ]
    return {"items": members, "total": total, "page": page, "page_size": page_size}


@router.post("/{slug}/members", status_code=status.HTTP_201_CREATED, response_model=MemberResponse)
async def add_member(
    slug: str,
    hotkey: str,
    role: OrgRole = OrgRole.VIEWER,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> MemberResponse:
    org = await _get_org_by_slug(db, slug)
    await _require_role(db, publisher, org.id, OrgRole.ADMIN)

    user = await _ensure_user(db, hotkey)

    # Check if already a member
    existing = await db.execute(
        select(MembershipRow).where(
            MembershipRow.user_id == user.id,
            MembershipRow.org_id == org.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "User already a member")

    mem = MembershipRow(user_id=user.id, org_id=org.id, role=role)
    db.add(mem)

    await log_audit(
        db,
        action=AuditAction.MEMBER_ADDED,
        resource_type="membership",
        resource_id=f"{org.id}:{user.id}",
        actor_hotkey=publisher,
        org_id=org.id,
        new_value={"hotkey": hotkey, "role": role.value},
    )

    await db.commit()
    return MemberResponse(user_id=user.id, hotkey=hotkey, role=role.value)


@router.patch("/{slug}/members/{member_hotkey}", response_model=MemberResponse)
async def update_member_role(
    slug: str,
    member_hotkey: str,
    role: OrgRole,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> MemberResponse:
    """Update a member's role (ADMIN only)."""
    org = await _get_org_by_slug(db, slug)
    await _require_role(db, publisher, org.id, OrgRole.ADMIN)

    target_user = (await db.execute(
        select(UserRow).where(UserRow.hotkey == member_hotkey)
    )).scalar_one_or_none()
    if not target_user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    membership = (await db.execute(
        select(MembershipRow).where(
            MembershipRow.user_id == target_user.id,
            MembershipRow.org_id == org.id,
        )
    )).scalar_one_or_none()
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User is not a member of this org")

    old_role = membership.role
    membership.role = role

    await log_audit(
        db,
        action=AuditAction.MEMBER_ROLE_CHANGED,
        resource_type="membership",
        resource_id=f"{org.id}:{target_user.id}",
        actor_hotkey=publisher,
        org_id=org.id,
        old_value={"role": old_role if isinstance(old_role, str) else old_role.value},
        new_value={"role": role.value},
    )

    await db.commit()
    return MemberResponse(user_id=target_user.id, hotkey=member_hotkey, role=role.value)


@router.delete("/{slug}/members/{member_hotkey}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    slug: str,
    member_hotkey: str,
    db: AsyncSession = Depends(get_db),
    publisher: str = Depends(verify_publisher),
) -> None:
    """Remove a member from the organization (ADMIN only).

    Admins cannot remove themselves — transfer ownership first.
    """
    org = await _get_org_by_slug(db, slug)
    await _require_role(db, publisher, org.id, OrgRole.ADMIN)

    if member_hotkey == publisher:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot remove yourself — transfer admin role to another member first",
        )

    target_user = (await db.execute(
        select(UserRow).where(UserRow.hotkey == member_hotkey)
    )).scalar_one_or_none()
    if not target_user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    membership = (await db.execute(
        select(MembershipRow).where(
            MembershipRow.user_id == target_user.id,
            MembershipRow.org_id == org.id,
        )
    )).scalar_one_or_none()
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User is not a member of this org")

    await db.delete(membership)

    await log_audit(
        db,
        action=AuditAction.MEMBER_REMOVED,
        resource_type="membership",
        resource_id=f"{org.id}:{target_user.id}",
        actor_hotkey=publisher,
        org_id=org.id,
        old_value={"hotkey": member_hotkey, "role": membership.role if isinstance(membership.role, str) else membership.role.value},
    )

    await db.commit()


# ── Helpers ─────────────────────────────────────────────────

async def _ensure_user(db: AsyncSession, hotkey: str) -> UserRow:
    """Get or create a user by hotkey."""
    result = await db.execute(select(UserRow).where(UserRow.hotkey == hotkey))
    user = result.scalar_one_or_none()
    if not user:
        user = UserRow(hotkey=hotkey)
        db.add(user)
        await db.flush()
    return user


async def _get_org_by_slug(db: AsyncSession, slug: str) -> OrganizationRow:
    result = await db.execute(
        select(OrganizationRow).where(OrganizationRow.slug == slug)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return org


async def _require_role(
    db: AsyncSession, hotkey: str, org_id: int, min_role: OrgRole
) -> MembershipRow:
    """Ensure the caller has at least the given role in the org."""
    user = await db.execute(select(UserRow).where(UserRow.hotkey == hotkey))
    user_row = user.scalar_one_or_none()
    if not user_row:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this org")

    result = await db.execute(
        select(MembershipRow).where(
            MembershipRow.user_id == user_row.id,
            MembershipRow.org_id == org_id,
        )
    )
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this org")

    role_hierarchy = {OrgRole.VIEWER: 0, OrgRole.EDITOR: 1, OrgRole.ADMIN: 2}
    if role_hierarchy.get(OrgRole(mem.role), 0) < role_hierarchy.get(min_role, 0):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Requires {min_role.value} role, you have {mem.role}",
        )
    return mem


async def require_org_member(
    db: AsyncSession, hotkey: str, org_id: int,
) -> MembershipRow:
    """Verify the caller is at least a VIEWER in the given org."""
    return await _require_role(db, hotkey, org_id, OrgRole.VIEWER)
