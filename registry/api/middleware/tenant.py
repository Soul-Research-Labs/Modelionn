"""Tenant resolution middleware — multi-tenancy via org context.

Resolves the current organization from:
1. X-Org-Slug request header (highest priority)
2. Default org (for backward compatibility, no header = no org filter)

Stores the resolved org_id in a ContextVar for downstream use.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ContextVars for request-scoped tenant info
current_org_id: ContextVar[int | None] = ContextVar("current_org_id", default=None)
current_org_slug: ContextVar[str] = ContextVar("current_org_slug", default="")


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract org context from request headers.

    Note: This middleware only sets ContextVars. Actual org resolution
    (slug → org_id lookup) is done at the route/dependency level
    since it requires a DB session.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        slug = request.headers.get("x-org-slug", "")
        slug_token = current_org_slug.set(slug)
        org_token = current_org_id.set(None)  # Will be resolved by dependency
        try:
            response: Response = await call_next(request)
            return response
        finally:
            current_org_slug.reset(slug_token)
            current_org_id.reset(org_token)
