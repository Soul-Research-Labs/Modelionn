"""Database engine and session management."""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from registry.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session  # type: ignore[misc]


@asynccontextmanager
async def get_async_session():
    """Standalone async context manager for use outside of FastAPI dependency injection."""
    async with async_session() as session:
        yield session
