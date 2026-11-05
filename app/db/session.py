"""Async database engine and session dependency."""
import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///:memory:"
)

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["poolclass"] = StaticPool
    if ":memory:" in DATABASE_URL:
        _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from app.models.domain import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    from app.models.domain import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def create_test_db() -> None:
    """Reset schema and in-memory runtime state for hermetic test isolation."""
    from app.core.ratelimit import rate_limiter
    from app.engine.book import reset_sequence_state
    from app.models.domain import Base
    from app.ws.sequence import stream_sequencer

    rate_limiter.reset()
    reset_sequence_state()
    stream_sequencer.reset()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
