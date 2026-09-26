"""Pytest fixtures for unit and integration testing."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.attest.api.dependencies import (
    get_contract_registry,
    get_db,
    get_downstream_client,
    get_verifier_client,
)
from src.attest.app import app
from src.attest.contracts import ContractRegistry, load_contracts
from src.attest.models.action import Base
from src.downstream_mock.app import app as mock_app
from src.downstream_mock.store import store

# In-memory SQLite async engine for fast unit tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean isolated database session for each test."""
    store.reset()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX AsyncClient with dependencies overridden for unit testing."""
    store.reset()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    contracts = load_contracts("contracts")
    registry = ContractRegistry(contracts)

    def override_registry() -> ContractRegistry:
        return registry

    mock_transport = ASGITransport(app=mock_app)
    downstream_mock_client = AsyncClient(transport=mock_transport, base_url="http://mock")
    verifier_mock_client = AsyncClient(transport=mock_transport, base_url="http://mock")

    async def override_downstream() -> AsyncClient:
        return downstream_mock_client

    async def override_verifier() -> AsyncClient:
        return verifier_mock_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_contract_registry] = override_registry
    app.dependency_overrides[get_downstream_client] = override_downstream
    app.dependency_overrides[get_verifier_client] = override_verifier

    gateway_transport = ASGITransport(app=app)
    async with AsyncClient(transport=gateway_transport, base_url="http://test") as ac:
        yield ac

    await downstream_mock_client.aclose()
    await verifier_mock_client.aclose()
    app.dependency_overrides.clear()
