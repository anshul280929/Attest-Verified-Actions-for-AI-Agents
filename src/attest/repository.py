"""Repository layer for atomic action lifecycle and append-only audit events."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.attest.models.action import Action, ActionEvent, Outbox
from src.attest.state_machine import ActionState, transition


class ActionNotFoundError(Exception):
    """Raised when an action is not found by ID or key."""


class StateMismatchError(Exception):
    """Raised when an action's current state does not match the expected from_state."""


class ActionRepository:
    """Manages transactional persistence for Actions, ActionEvents, and Outbox entries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_action(
        self,
        task_id: str,
        step: int,
        tool: str,
        resource_key: str,
        args: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[Action, bool]:
        """Record an action in the RECEIVED state.

        Returns:
            tuple[Action, bool]: (action, deduplicated)
            If the idempotency key already exists, returns the existing action with deduplicated=True.
        """
        # First check if action already exists with this idempotency key
        existing = await self.get_action_by_key(idempotency_key)
        if existing is not None:
            return existing, True

        action_id = uuid.uuid4()
        new_action = Action(
            id=action_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            step=step,
            tool=tool,
            resource_key=resource_key,
            args=args,
            state=ActionState.RECEIVED.value,
            attempts=0,
        )

        initial_event = ActionEvent(
            action_id=action_id,
            from_state=None,
            to_state=ActionState.RECEIVED.value,
            detail={"event": "action_recorded", "tool": tool},
        )

        try:
            self.session.add(new_action)
            self.session.add(initial_event)
            await self.session.commit()
            await self.session.refresh(new_action, ["events"])
            return new_action, False
        except IntegrityError:
            await self.session.rollback()
            # Concurrent insert could have committed; fetch the existing record
            existing = await self.get_action_by_key(idempotency_key)
            if existing is not None:
                return existing, True
            raise

    async def transition_action(
        self,
        action_id: uuid.UUID,
        from_state: ActionState | str | None,
        to_state: ActionState | str,
        detail: dict[str, Any] | None = None,
        outbox_kind: str | None = None,
    ) -> Action:
        """Atomically transition an action to a new state and record the audit event.

        Optionally inserts an outbox entry in the same transaction.

        Raises:
            ActionNotFoundError: If action does not exist.
            StateMismatchError: If current state does not match expected from_state.
            IllegalTransitionError: If the transition violates state machine rules.
        """
        stmt = (
            select(Action)
            .where(Action.id == action_id)
            .options(selectinload(Action.events))
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        action = result.scalar_one_or_none()

        if action is None:
            raise ActionNotFoundError(f"Action {action_id} not found")

        current_enum = ActionState(action.state)
        target_enum = ActionState(to_state)

        if from_state is not None:
            expected_enum = ActionState(from_state)
            if current_enum != expected_enum:
                raise StateMismatchError(
                    f"Action {action_id} is in state {current_enum.value}, expected {expected_enum.value}"
                )

        # Enforce state machine rules
        transition(current_enum, target_enum)

        # Update action
        action.state = target_enum.value

        # Append audit event
        event = ActionEvent(
            action_id=action.id,
            from_state=current_enum.value,
            to_state=target_enum.value,
            detail=detail,
        )
        self.session.add(event)

        # Add outbox entry if required (e.g. 'reconcile' or 'compensate')
        if outbox_kind:
            outbox_entry = Outbox(
                action_id=action.id,
                kind=outbox_kind,
            )
            self.session.add(outbox_entry)

        await self.session.commit()
        await self.session.refresh(action, ["events"])
        return action

    async def get_action(self, action_id: uuid.UUID) -> Action | None:
        """Fetch an action and its full audit event history by ID."""
        stmt = select(Action).where(Action.id == action_id).options(selectinload(Action.events))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_action_by_key(self, idempotency_key: str) -> Action | None:
        """Fetch an action and its events by idempotency key."""
        stmt = (
            select(Action)
            .where(Action.idempotency_key == idempotency_key)
            .options(selectinload(Action.events))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
