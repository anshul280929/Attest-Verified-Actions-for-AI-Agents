"""FastAPI router for action ingestion and status inspection."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import DBAPIError, OperationalError

from src.attest.api.dependencies import get_repository
from src.attest.idempotency import derive_key
from src.attest.repository import ActionRepository
from src.attest.schemas.action import (
    ActionCreateRequest,
    ActionDetailResponse,
    ActionEventResponse,
    ActionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/actions", tags=["actions"])


@router.post(
    "",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Record an action in the durable ledger",
)
async def create_action(
    payload: ActionCreateRequest,
    repo: Annotated[ActionRepository, Depends(get_repository)],
) -> ActionResponse:
    """Durably record an action in RECEIVED state before downstream execution.

    If an identical action has already been submitted (matching idempotency key),
    returns the existing action with deduplicated=True.

    If the ledger write fails, returns 503 and blocks execution (Ledger Guard).
    """
    idempotency_key = derive_key(
        task_id=payload.task_id,
        step=payload.step,
        tool=payload.tool,
        args=payload.args,
    )

    try:
        action, deduplicated = await repo.create_action(
            task_id=payload.task_id,
            step=payload.step,
            tool=payload.tool,
            resource_key=payload.resource_key,
            args=payload.args,
            idempotency_key=idempotency_key,
        )
    except (OperationalError, DBAPIError, OSError) as exc:
        logger.error(f"Ledger guard triggered: database write failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ledger_unavailable",
                "message": "Cannot record action; execution blocked",
            },
        ) from exc
    except Exception as exc:
        logger.error(f"Unexpected error recording action: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ledger_unavailable",
                "message": "Cannot record action; execution blocked",
            },
        ) from exc

    return ActionResponse(
        action_id=action.id,
        idempotency_key=action.idempotency_key,
        state=action.state,
        verdict=None,
        message="action recorded" if not deduplicated else "action already exists (deduplicated)",
        deduplicated=deduplicated,
    )


@router.get(
    "/{action_id}",
    response_model=ActionDetailResponse,
    summary="Retrieve an action and its full audit event history",
)
async def get_action(
    action_id: uuid.UUID,
    repo: Annotated[ActionRepository, Depends(get_repository)],
) -> ActionDetailResponse:
    """Retrieve an action and its append-only transition event trail."""
    action = await repo.get_action(action_id)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action with ID {action_id} not found",
        )

    return ActionDetailResponse(
        action_id=action.id,
        idempotency_key=action.idempotency_key,
        task_id=action.task_id,
        step=action.step,
        tool=action.tool,
        resource_key=action.resource_key,
        args=action.args,
        state=action.state,
        verdict=None,
        attempts=action.attempts,
        downstream_ref=action.downstream_ref,
        created_at=action.created_at,
        updated_at=action.updated_at,
        events=[
            ActionEventResponse(
                id=event.id,
                from_state=event.from_state,
                to_state=event.to_state,
                detail=event.detail,
                at=event.at,
            )
            for event in action.events
        ],
    )
