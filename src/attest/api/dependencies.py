"""FastAPI dependency injection providers."""

from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.attest.clients import create_downstream_client, create_verifier_client
from src.attest.contracts import ContractRegistry, load_contracts
from src.attest.database import get_db
from src.attest.repository import ActionRepository


async def get_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ActionRepository:
    """Dependency that injects an ActionRepository with the active session."""
    return ActionRepository(session)


def get_contract_registry(request: Request) -> ContractRegistry:
    """Dependency that injects the validated ContractRegistry."""
    registry = getattr(request.app.state, "contract_registry", None)
    if registry is None:
        try:
            contracts = load_contracts("contracts")
        except Exception:
            contracts = {}
        registry = ContractRegistry(contracts)
        request.app.state.contract_registry = registry
    return registry


async def get_downstream_client(request: Request) -> httpx.AsyncClient:
    """Dependency that injects the downstream write client."""
    client = getattr(request.app.state, "downstream_client", None)
    if client is None:
        client = create_downstream_client()
    return client


async def get_verifier_client(request: Request) -> httpx.AsyncClient:
    """Dependency that injects the independent verification read client."""
    client = getattr(request.app.state, "verifier_client", None)
    if client is None:
        client = create_verifier_client()
    return client
