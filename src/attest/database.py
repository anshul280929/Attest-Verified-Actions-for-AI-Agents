"""Database engine and session management using SQLAlchemy AsyncIO."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.attest.config import settings

# In production or local Postgres: postgresql+asyncpg://
# SQLite is supported for fast unit testing (sqlite+aiosqlite://)
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level.upper() == "DEBUG",
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
