"""Multi-tenant middleware isolation tests — verify that concurrent requests
with different X-Org-Slug headers do not leak context across requests."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from registry.api.middleware.tenant import TenantMiddleware, current_org_slug, current_org_id


# ---------------------------------------------------------------------------
# Setup — small app that records ContextVar at arrival and after a sleep
# ---------------------------------------------------------------------------

def _make_tenant_app() -> FastAPI:
    app = FastAPI()

    @app.get("/tenant")
    async def _get_tenant():
        slug_at_start = current_org_slug.get()
        org_id_at_start = current_org_id.get()
        # Simulate an async DB lookup in the middle of request handling
        await asyncio.sleep(0.05)
        slug_after_io = current_org_slug.get()
        return {
            "slug_start": slug_at_start,
            "slug_after_io": slug_after_io,
            "org_id": org_id_at_start,
        }

    app.add_middleware(TenantMiddleware)
    return app


@pytest.fixture()
async def client():
    app = _make_tenant_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    async def test_no_header_returns_empty_slug(self, client: AsyncClient):
        resp = await client.get("/tenant")
        body = resp.json()
        assert body["slug_start"] == ""
        assert body["slug_after_io"] == ""
        assert body["org_id"] is None

    async def test_header_sets_slug(self, client: AsyncClient):
        resp = await client.get("/tenant", headers={"x-org-slug": "acme"})
        body = resp.json()
        assert body["slug_start"] == "acme"
        assert body["slug_after_io"] == "acme"

    async def test_concurrent_requests_isolated(self, client: AsyncClient):
        """Two concurrent requests with different slugs must not bleed."""
        resp_a, resp_b = await asyncio.gather(
            client.get("/tenant", headers={"x-org-slug": "org-alpha"}),
            client.get("/tenant", headers={"x-org-slug": "org-beta"}),
        )

        a = resp_a.json()
        b = resp_b.json()

        # Each request must see its own slug throughout
        assert a["slug_start"] == "org-alpha"
        assert a["slug_after_io"] == "org-alpha"
        assert b["slug_start"] == "org-beta"
        assert b["slug_after_io"] == "org-beta"

    async def test_slug_reset_after_request(self, client: AsyncClient):
        """After a request completes, the ContextVar should not persist."""
        await client.get("/tenant", headers={"x-org-slug": "temp-org"})
        # In a fresh request with no header, slug must be empty
        resp = await client.get("/tenant")
        assert resp.json()["slug_start"] == ""

    async def test_special_characters_in_slug(self, client: AsyncClient):
        """Slug with hyphens, numbers, and underscores should pass through."""
        resp = await client.get("/tenant", headers={"x-org-slug": "my-org_123"})
        assert resp.json()["slug_start"] == "my-org_123"
