import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

# Teammate 4: DATABASE_URL from env is preferred.
# Falls back to local dev URL from alembic.ini if not set.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql+asyncpg://sentinel:change_me_strong_password@localhost:5432/sentinel"
)

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
