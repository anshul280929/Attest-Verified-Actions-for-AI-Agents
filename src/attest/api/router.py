"""FastAPI router for action ingestion, execution, verification, and status inspection."""

import logging
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import DBAPIError, OperationalError

from src.attest.api.dependencies import (
    get_contract_registry,
    get_downstream_client,
    get_repository,
    get_verifier_client,
)
from src.attest.contracts import ContractRegistry
from src.attest.executor import execute_contract
from src.attest.idempotency import derive_key
from src.attest.repository import ActionRepository
from src.attest.schemas.action import (
    ActionCreateRequest,
    ActionDetailResponse,
    ActionEventResponse,
    ActionResponse,
)
from src.attest.state_machine import ActionState
from src.attest.verifier import verify_postcondition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/actions", tags=["actions"])


def _state_to_verdict(state: str) -> str | None:
    """Map action state to high-level model-readable verdict."""
    if state == ActionState.VERIFIED.value:
        return "VERIFIED"
    if state in {
        ActionState.FAILED.value,
        ActionState.COMPENSATING.value,
        ActionState.COMPENSATED.value,
    }:
        return "FAILED"
    if state in {ActionState.UNKNOWN.value, ActionState.NEEDS_REVIEW.value}:
        return "UNKNOWN"
    return None


@router.post(
    "",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Record, execute, and verify an action",
)
async def create_action(
    payload: ActionCreateRequest,
    request: Request,
    repo: Annotated[ActionRepository, Depends(get_repository)],
    registry: Annotated[ContractRegistry, Depends(get_contract_registry)],
    downstream_client: Annotated[httpx.AsyncClient, Depends(get_downstream_client)],
    verifier_client: Annotated[httpx.AsyncClient, Depends(get_verifier_client)],
) -> ActionResponse:
    """Submit an action through the Attest verification pipeline.

    1. Validates contract exists for tool; returns 422 if unknown.
    2. Atomically records action in RECEIVED state (Ledger Guard).
    3. If deduplicated, immediately returns existing record.
    4. Executes downstream mutation with Idempotency-Key.
    5. Classifies response and transitions state:
       - definite_success -> EXECUTED -> independent read postcondition check -> VERIFIED/FAILED/COMPENSATING
       - definite_failure -> FAILED
       - ambiguous -> UNKNOWN (with reconciliation outbox row)
    """
    # 1. Validate contract existence
    contract = registry.get(payload.tool)
    if contract is None:
        known_tools = sorted(list(registry.contracts.keys()))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "unknown_tool",
                "message": f"No contract registered for tool '{payload.tool}'. Known tools: {known_tools}",
            },
        )

    # 2. Derive deterministic idempotency key
    idempotency_key = derive_key(
        task_id=payload.task_id,
        step=payload.step,
        tool=payload.tool,
        args=payload.args,
    )

    # 3. Durably record in RECEIVED (Ledger Guard)
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

    # If deduplicated, do not re-execute downstream
    if deduplicated:
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict=_state_to_verdict(action.state),
            message="action already exists (deduplicated)",
            deduplicated=True,
        )

    # Extract any chaos testing headers to forward
    chaos_headers: dict[str, str] = {}
    for h in ("x-fault-profile", "x-chaos-profile", "x-seed"):
        val = request.headers.get(h)
        if val is not None:
            chaos_headers[h] = val

    # 4. Execute downstream mutation
    execution = await execute_contract(
        contract=contract,
        args=payload.args,
        idempotency_key=idempotency_key,
        client=downstream_client,
        extra_headers=chaos_headers,
    )

    # 5. Handle execution classification
    if execution.classification == "definite_failure":
        action = await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.RECEIVED,
            to_state=ActionState.FAILED,
            detail={
                "error": execution.error_detail,
                "status_code": execution.status_code,
            },
        )
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict="FAILED",
            message=f"action failed: {execution.error_detail}",
            deduplicated=False,
        )

    if execution.classification == "ambiguous":
        action = await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.RECEIVED,
            to_state=ActionState.UNKNOWN,
            detail={
                "error": execution.error_detail,
                "status_code": execution.status_code,
            },
            outbox_kind="reconcile",
        )
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict="UNKNOWN",
            message="pending confirmation",
            deduplicated=False,
        )

    # definite_success: Transition RECEIVED -> EXECUTED
    action = await repo.transition_action(
        action_id=action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.EXECUTED,
        detail={
            "status_code": execution.status_code,
            "downstream_ref": execution.downstream_ref,
        },
    )

    # 6. Independent verification read
    verification = await verify_postcondition(
        contract=contract,
        args=payload.args,
        client=verifier_client,
    )

    if verification.verdict == "VERIFIED":
        action = await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.EXECUTED,
            to_state=ActionState.VERIFIED,
            detail=verification.detail,
        )
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict="VERIFIED",
            message="action verified",
            deduplicated=False,
        )

    if verification.verdict == "COMPENSATING":
        action = await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.EXECUTED,
            to_state=ActionState.COMPENSATING,
            detail=verification.detail,
            outbox_kind="compensate",
        )
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict="FAILED",
            message="action failed, compensation initiated",
            deduplicated=False,
        )

    if verification.verdict == "FAILED":
        action = await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.EXECUTED,
            to_state=ActionState.FAILED,
            detail=verification.detail,
        )
        return ActionResponse(
            action_id=action.id,
            idempotency_key=action.idempotency_key,
            state=action.state,
            verdict="FAILED",
            message=f"action postcondition violated: {verification.failing_assertion}",
            deduplicated=False,
        )

    # verification.verdict == "UNKNOWN" (read path unavailable)
    action = await repo.transition_action(
        action_id=action.id,
        from_state=ActionState.EXECUTED,
        to_state=ActionState.UNKNOWN,
        detail=verification.detail,
        outbox_kind="reconcile",
    )
    return ActionResponse(
        action_id=action.id,
        idempotency_key=action.idempotency_key,
        state=action.state,
        verdict="UNKNOWN",
        message="pending confirmation",
        deduplicated=False,
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
        verdict=_state_to_verdict(action.state),
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
