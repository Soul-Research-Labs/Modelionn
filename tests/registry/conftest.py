"""Shared fixtures for registry API tests — in-memory SQLite + ASGI transport."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from registry.models.database import Base
from registry.core.deps import get_db

# Use an in-memory SQLite database for test isolation.
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Pre-mock the Celery task modules so importing them doesn't connect to a broker.
_mock_dispatch = MagicMock()
_mock_dispatch.delay = MagicMock(return_value=None)
_mock_task_module = MagicMock()
_mock_task_module.dispatch_proof_job = _mock_dispatch

_mock_celery_app = MagicMock()

if "registry.tasks.celery_app" not in sys.modules:
    sys.modules["registry.tasks.celery_app"] = _mock_celery_app
if "registry.tasks.proof_dispatch" not in sys.modules:
    sys.modules["registry.tasks.proof_dispatch"] = _mock_task_module


@pytest.fixture()
async def db_engine():
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture()
async def client(db_engine):
    """Async HTTP test client wired to an in-memory DB."""
    from registry.api.routes.circuits import router as circuits_router
    from registry.api.routes.proofs import router as proofs_router
    from registry.api.routes.provers import router as provers_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(circuits_router, prefix="/circuits")
    app.include_router(proofs_router, prefix="/proofs")
    app.include_router(provers_router, prefix="/provers")

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
