from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            get_settings().sqlalchemy_url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Services commit explicitly; an unhandled error rolls back."""
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def worker_sessionmaker(url: str | None = None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Per-task engine for Celery: each ``asyncio.run`` gets its own event loop,
    so pooled asyncpg connections must not be shared between tasks."""
    engine = create_async_engine(url or get_settings().sqlalchemy_url, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
