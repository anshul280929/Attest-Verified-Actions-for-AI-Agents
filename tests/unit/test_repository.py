"""Unit tests for ActionRepository and transactional audit trail transitions."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.attest.idempotency import derive_key
from src.attest.repository import ActionRepository, StateMismatchError
from src.attest.state_machine import ActionState, IllegalTransitionError


@pytest.mark.asyncio
async def test_create_and_transition_action(test_session: AsyncSession) -> None:
    """Create action and perform valid transition chain: RECEIVED -> EXECUTED -> VERIFIED."""
    repo = ActionRepository(test_session)
    key = derive_key("task-repo-1", 1, "issue_refund", {"order_id": "ord-1"})

    action, dedup = await repo.create_action(
        task_id="task-repo-1",
        step=1,
        tool="issue_refund",
        resource_key="ord-1",
        args={"order_id": "ord-1"},
        idempotency_key=key,
    )
    assert not dedup
    assert action.state == ActionState.RECEIVED.value
    assert len(action.events) == 1
    assert action.events[0].from_state is None
    assert action.events[0].to_state == ActionState.RECEIVED.value

    # Transition 1: RECEIVED -> EXECUTED
    action = await repo.transition_action(
        action_id=action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.EXECUTED,
        detail={"status_code": 200},
    )
    assert action.state == ActionState.EXECUTED.value
    assert len(action.events) == 2
    assert action.events[1].from_state == ActionState.RECEIVED.value
    assert action.events[1].to_state == ActionState.EXECUTED.value

    # Transition 2: EXECUTED -> VERIFIED
    action = await repo.transition_action(
        action_id=action.id,
        from_state=ActionState.EXECUTED,
        to_state=ActionState.VERIFIED,
        detail={"verified": True, "read_amount": 100.0},
    )
    assert action.state == ActionState.VERIFIED.value
    assert len(action.events) == 3
    assert action.events[2].from_state == ActionState.EXECUTED.value
    assert action.events[2].to_state == ActionState.VERIFIED.value


@pytest.mark.asyncio
async def test_illegal_transition_rejection(test_session: AsyncSession) -> None:
    """Attempting illegal transition raises IllegalTransitionError and does NOT append event."""
    repo = ActionRepository(test_session)
    key = derive_key("task-repo-2", 1, "issue_refund", {"order_id": "ord-2"})

    action, _ = await repo.create_action(
        task_id="task-repo-2",
        step=1,
        tool="issue_refund",
        resource_key="ord-2",
        args={"order_id": "ord-2"},
        idempotency_key=key,
    )
    assert len(action.events) == 1

    # Illegal: cannot jump RECEIVED -> VERIFIED directly
    with pytest.raises(IllegalTransitionError):
        await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.RECEIVED,
            to_state=ActionState.VERIFIED,
        )

    # Re-fetch from DB: verify state remained RECEIVED and events count is still 1
    fetched = await repo.get_action(action.id)
    assert fetched is not None
    assert fetched.state == ActionState.RECEIVED.value
    assert len(fetched.events) == 1


@pytest.mark.asyncio
async def test_state_mismatch_rejection(test_session: AsyncSession) -> None:
    """If expected from_state does not match action current state, StateMismatchError is raised."""
    repo = ActionRepository(test_session)
    key = derive_key("task-repo-3", 1, "issue_refund", {"order_id": "ord-3"})

    action, _ = await repo.create_action(
        task_id="task-repo-3",
        step=1,
        tool="issue_refund",
        resource_key="ord-3",
        args={"order_id": "ord-3"},
        idempotency_key=key,
    )

    # Action is in RECEIVED, but caller expects EXECUTED
    with pytest.raises(StateMismatchError):
        await repo.transition_action(
            action_id=action.id,
            from_state=ActionState.EXECUTED,
            to_state=ActionState.VERIFIED,
        )


@pytest.mark.asyncio
async def test_transition_with_outbox_entry(test_session: AsyncSession) -> None:
    """Transitioning to UNKNOWN appends an outbox row for asynchronous reconciliation."""
    repo = ActionRepository(test_session)
    key = derive_key("task-repo-4", 1, "issue_refund", {"order_id": "ord-4"})

    action, _ = await repo.create_action(
        task_id="task-repo-4",
        step=1,
        tool="issue_refund",
        resource_key="ord-4",
        args={"order_id": "ord-4"},
        idempotency_key=key,
    )

    # RECEIVED -> UNKNOWN with outbox kind 'reconcile'
    action = await repo.transition_action(
        action_id=action.id,
        from_state=ActionState.RECEIVED,
        to_state=ActionState.UNKNOWN,
        detail={"error": "downstream_timeout"},
        outbox_kind="reconcile",
    )
    assert action.state == ActionState.UNKNOWN.value
    assert len(action.events) == 2
    assert action.events[1].to_state == ActionState.UNKNOWN.value
