import os
from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine,
)
from typing import AsyncGenerator, Tuple

# Teammate 4: DATABASE_URL from env is preferred.
# Falls back to local dev URL from alembic.ini if not set.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://sentinel:change_me_strong_password@localhost:5432/sentinel"
)

# FastAPI (uvicorn) runs a single long-lived event loop for the life of the
# process, so a module-level engine/sessionmaker is safe here and is what
# `get_db` (the FastAPI dependency) uses below.
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions in FastAPI."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def build_session_factory() -> Tuple[AsyncEngine, async_sessionmaker]:
    """
    Build a brand-new AsyncEngine + sessionmaker pair.

    Celery (prefork) tasks call `asyncio.run(...)` per invocation, which opens
    and tears down a fresh event loop every time. asyncpg's connection pool is
    bound to the loop that created it, so a module-level engine reused across
    separate asyncio.run() calls raises "RuntimeError: Event loop is closed"
    on every task run after the first. Celery tasks must call this inside
    their coroutine, use the returned sessionmaker, and `await engine.dispose()`
    before the coroutine returns — never hold the engine at module scope.
    """
    task_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    task_session_local = async_sessionmaker(
        bind=task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return task_engine, task_session_local
