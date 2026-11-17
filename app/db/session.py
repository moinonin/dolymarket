"""Async database engine and session dependency (supports aiosqlite, asyncpg, and Turso libSQL)."""
import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

RAW_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///./dolymarket.db"
).strip()
DATABASE_TOKEN = (
    os.environ.get("DATABASE_TOKEN") or os.environ.get("TURSO_AUTH_TOKEN") or ""
).strip()

IS_LIBSQL = RAW_DATABASE_URL.startswith(("libsql://", "sqlite+libsql://"))

if RAW_DATABASE_URL.startswith("libsql://"):
    _host = RAW_DATABASE_URL.removeprefix("libsql://").rstrip("/")
    DATABASE_URL = f"sqlite+libsql://{_host}?secure=true"
else:
    DATABASE_URL = RAW_DATABASE_URL


class _LibsqlAsyncSession:
    """Async-compatible adapter over a sync SQLAlchemy Session for Turso libSQL."""

    def __init__(self, sync_session: Session) -> None:
        self._s = sync_session
        self.info: dict[str, Any] = {}

    def add(self, instance: Any) -> None:
        self._s.add(instance)

    def add_all(self, instances: Any) -> None:
        self._s.add_all(instances)

    async def _run_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(3):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except ValueError as exc:
                msg = str(exc)
                if attempt < 2 and ("Hrana:" in msg or "connection closed" in msg):
                    await asyncio.to_thread(self._s.rollback)
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def execute(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._run_retry(self._s.execute, statement, params, **kwargs)

    async def scalar(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._run_retry(self._s.scalar, statement, params, **kwargs)

    async def scalars(self, statement: Any, params: Any = None, **kwargs: Any) -> Any:
        return await self._run_retry(self._s.scalars, statement, params, **kwargs)

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        return await self._run_retry(self._s.get, entity, ident, **kwargs)

    async def delete(self, instance: Any) -> None:
        await asyncio.to_thread(self._s.delete, instance)

    async def flush(self, objects: Any = None) -> None:
        await asyncio.to_thread(self._s.flush, objects)

    async def refresh(self, instance: Any, **kwargs: Any) -> None:
        await asyncio.to_thread(self._s.refresh, instance, **kwargs)

    async def commit(self) -> None:
        await asyncio.to_thread(self._s.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._s.rollback)

    async def close(self) -> None:
        await asyncio.to_thread(self._s.close)

    async def __aenter__(self) -> "_LibsqlAsyncSession":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        await self.close()


class _LibsqlSessionFactory:
    def __init__(self, sync_factory: sessionmaker) -> None:
        self._factory = sync_factory

    def __call__(self) -> _LibsqlAsyncSession:
        return _LibsqlAsyncSession(self._factory())


if IS_LIBSQL:
    _connect_args = {"auth_token": DATABASE_TOKEN} if DATABASE_TOKEN else {}
    engine = create_engine(DATABASE_URL, poolclass=NullPool, connect_args=_connect_args)
    _SyncSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    AsyncSessionLocal = _LibsqlSessionFactory(_SyncSessionLocal)
else:
    _engine_kwargs: dict = {}
    if DATABASE_URL.startswith("sqlite"):
        _engine_kwargs["poolclass"] = StaticPool
        _engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


def queue_post_commit(session: Any, callback: Any) -> None:
    """Register an async zero-arg callback to run only after session.commit() succeeds."""
    info = getattr(session, "info", None)
    if isinstance(info, dict):
        info.setdefault("post_commit_callbacks", []).append(callback)


async def get_async_session() -> AsyncIterator[AsyncSession | _LibsqlAsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            if isinstance(getattr(session, "info", None), dict):
                session.info.pop("post_commit_callbacks", None)
            await session.rollback()
            raise
        callbacks = (
            session.info.pop("post_commit_callbacks", [])
            if isinstance(getattr(session, "info", None), dict)
            else []
        )
        for cb in callbacks:
            try:
                await cb()
            except Exception:
                import logging

                logging.getLogger("app.db").exception("post_commit callback failed")


async def init_db() -> None:
    from app.models.domain import Base

    if IS_LIBSQL:
        await asyncio.to_thread(Base.metadata.create_all, engine)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    from app.models.domain import Base

    if IS_LIBSQL:
        await asyncio.to_thread(Base.metadata.drop_all, engine)
    else:
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
    if IS_LIBSQL:
        await asyncio.to_thread(Base.metadata.drop_all, engine)
        await asyncio.to_thread(Base.metadata.create_all, engine)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
