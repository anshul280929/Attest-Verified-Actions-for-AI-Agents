"""Integration test fixtures with real database and service integration."""

import logging
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.attest.app import app
from src.attest.config import settings
from src.attest.database import get_db
from src.attest.models.action import Base
from src.downstream_mock.app import app as mock_app

logger = logging.getLogger("attest.integration_tests")

# Try to connect to Postgres; if unavailable, use local persistent SQLite
POSTGRES_URL = settings.database_url
SQLITE_FALLBACK_URL = "sqlite+aiosqlite:///integration_test.db"


async def check_database_connection(url: str) -> bool:
    try:
        engine = create_async_engine(url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="session")
async def integration_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create integration test engine, targeting PostgreSQL if available."""
    is_postgres_up = await check_database_connection(POSTGRES_URL)
    if is_postgres_up:
        active_url = POSTGRES_URL
        logger.info(f"Integration tests running against PostgreSQL at {POSTGRES_URL}")
    else:
        active_url = SQLITE_FALLBACK_URL
        logger.info(
            f"PostgreSQL not reachable; running integration tests against {SQLITE_FALLBACK_URL}"
        )

    engine = create_async_engine(active_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def integration_session(
    integration_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated database session per integration test."""
    session_factory = async_sessionmaker(
        bind=integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def gateway_client(integration_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client talking to the Attest gateway with integration DB."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield integration_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://gateway.attest.local") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def downstream_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client talking to the downstream mock service."""
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://mock.downstream.local") as client:
        yield client
