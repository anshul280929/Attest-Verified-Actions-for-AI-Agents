"""FastAPI dependency injection providers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.attest.database import get_db
from src.attest.repository import ActionRepository


async def get_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ActionRepository:
    """Dependency that injects an ActionRepository with the active session."""
    return ActionRepository(session)
