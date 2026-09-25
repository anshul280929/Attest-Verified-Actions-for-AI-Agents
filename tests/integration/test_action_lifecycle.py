"""Integration tests verifying full action lifecycle and state machine safety properties.

Validates:
- LEDG-01: Action persisted before tool execution
- LEDG-02 / LEDG-03: Idempotent submission and deduplication
- LEDG-04: Append-only audit trail
- LEDG-05 / LEDG-06: Strict legal transitions, terminal immutability, and retry constraints
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.attest.models.action import Action, ActionEvent
from src.attest.repository import ActionRepository
from src.attest.state_machine import ActionState, IllegalTransitionError


@pytest.mark.asyncio
async def test_durable_recording_before_execution(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """LEDG-01: An action submission is immediately persisted to the ledger in RECEIVED state."""
    task_id = f"task-durable-{uuid.uuid4().hex[:6]}"
    payload = {
        "task_id": task_id,
        "step": 1,
        "tool": "issue_refund",
        "resource_key": "order-durable-1",
        "args": {"order_id": "order-durable-1", "amount": 55.0},
    }

    resp = await gateway_client.post("/v1/actions", json=payload)
    assert resp.status_code == 200
    action_id = uuid.UUID(resp.json()["action_id"])

    # Directly inspect database row outside gateway
    stmt = select(Action).where(Action.id == action_id)
    result = await integration_session.execute(stmt)
    action_row = result.scalar_one_or_none()

    assert action_row is not None
    assert action_row.task_id == task_id
    assert action_row.state == ActionState.RECEIVED.value
    assert action_row.tool == "issue_refund"


@pytest.mark.asyncio
async def test_idempotent_submission_deduplication(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """LEDG-02 & LEDG-03: Repeated submission with same key returns original action and single row."""
    task_id = f"task-idem-{uuid.uuid4().hex[:6]}"
    payload = {
        "task_id": task_id,
        "step": 2,
        "tool": "cancel_order",
        "resource_key": "order-idem-1",
        "args": {"order_id": "order-idem-1"},
    }

    # First submission
    resp1 = await gateway_client.post("/v1/actions", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["deduplicated"] is False
    action_id = uuid.UUID(data1["action_id"])

    # Second identical submission
    resp2 = await gateway_client.post("/v1/actions", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["deduplicated"] is True
    assert data2["action_id"] == str(action_id)

    # Verify database has exactly one row with this idempotency key
    stmt = select(Action).where(Action.idempotency_key == data1["idempotency_key"])
    rows = (await integration_session.execute(stmt)).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_audit_event_trail_continuity(
    integration_session: AsyncSession,
) -> None:
    """LEDG-04: Transitions append an unbroken audit trail of events."""
    repo = ActionRepository(integration_session)
    action, _ = await repo.create_action(
        task_id="task-audit-1",
        step=1,
        tool="issue_refund",
        resource_key="order-audit-1",
        args={"order_id": "order-audit-1", "amount": 10.0},
        idempotency_key=f"key-audit-{uuid.uuid4().hex}",
    )

    # RECEIVED -> EXECUTED -> VERIFIED
    await repo.transition_action(
        action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.EXECUTED,
        detail={"response_code": 200},
    )
    await repo.transition_action(
        action.id,
        from_state=ActionState.EXECUTED,
        to_state=ActionState.VERIFIED,
        detail={"postcondition_met": True},
    )

    # Check events directly from database
    stmt = (
        select(ActionEvent).where(ActionEvent.action_id == action.id).order_by(ActionEvent.id.asc())
    )
    events = (await integration_session.execute(stmt)).scalars().all()

    assert len(events) == 3
    assert events[0].from_state is None
    assert events[0].to_state == ActionState.RECEIVED.value

    assert events[1].from_state == ActionState.RECEIVED.value
    assert events[1].to_state == ActionState.EXECUTED.value

    assert events[2].from_state == ActionState.EXECUTED.value
    assert events[2].to_state == ActionState.VERIFIED.value


@pytest.mark.asyncio
async def test_illegal_transition_and_terminal_immutability(
    integration_session: AsyncSession,
) -> None:
    """LEDG-05 & LEDG-06: Direct illegal moves and transitions out of terminal states are rejected."""
    repo = ActionRepository(integration_session)
    action, _ = await repo.create_action(
        task_id="task-immut-1",
        step=1,
        tool="issue_refund",
        resource_key="order-immut-1",
        args={"order_id": "order-immut-1"},
        idempotency_key=f"key-immut-{uuid.uuid4().hex}",
    )

    # Disallowed: jump from RECEIVED to VERIFIED
    with pytest.raises(IllegalTransitionError):
        await repo.transition_action(
            action.id,
            from_state=ActionState.RECEIVED,
            to_state=ActionState.VERIFIED,
        )

    # Valid path to terminal state: RECEIVED -> EXECUTED -> VERIFIED
    await repo.transition_action(
        action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.EXECUTED,
    )
    await repo.transition_action(
        action.id,
        from_state=ActionState.EXECUTED,
        to_state=ActionState.VERIFIED,
    )

    # From VERIFIED (terminal), any transition attempt fails
    with pytest.raises(IllegalTransitionError):
        await repo.transition_action(
            action.id,
            from_state=ActionState.VERIFIED,
            to_state=ActionState.FAILED,
        )


@pytest.mark.asyncio
async def test_retry_permitted_only_from_failed(
    integration_session: AsyncSession,
) -> None:
    """LEDG-06: Safe retry (transition back to RECEIVED) is allowed ONLY from FAILED."""
    repo = ActionRepository(integration_session)
    action, _ = await repo.create_action(
        task_id="task-retry-1",
        step=1,
        tool="issue_refund",
        resource_key="order-retry-1",
        args={"order_id": "order-retry-1"},
        idempotency_key=f"key-retry-{uuid.uuid4().hex}",
    )

    # Transition to UNKNOWN (ambiguous timeout)
    await repo.transition_action(
        action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.UNKNOWN,
    )

    # UNKNOWN cannot retry directly (must not blind retry!)
    with pytest.raises(IllegalTransitionError):
        await repo.transition_action(
            action.id,
            from_state=ActionState.UNKNOWN,
            to_state=ActionState.RECEIVED,
        )

    # Once reconciled to FAILED (no-effect confirmed)
    await repo.transition_action(
        action.id,
        from_state=ActionState.UNKNOWN,
        to_state=ActionState.FAILED,
    )

    # Safe retry from FAILED -> RECEIVED succeeds!
    retried = await repo.transition_action(
        action.id,
        from_state=ActionState.FAILED,
        to_state=ActionState.RECEIVED,
    )
    assert retried.state == ActionState.RECEIVED.value
