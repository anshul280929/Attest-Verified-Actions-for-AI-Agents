"""Exhaustive property-based and unit tests for the Attest Action State Machine.

Validates:
- LEDG-05: Strict state transition matrix enforcement
- LEDG-06: Terminal state immutability, retry rules, and event audit chaining
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule

from src.attest.state_machine import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    ActionState,
    IllegalTransitionError,
    is_legal_transition,
    transition,
)


def test_exhaustive_transition_matrix() -> None:
    """For every (from_s, to_s) in ActionState x ActionState:

    assert transition() succeeds iff (from_s, to_s) is in LEGAL_TRANSITIONS.
    """
    for from_s in ActionState:
        for to_s in ActionState:
            expected_legal = (from_s, to_s) in LEGAL_TRANSITIONS
            assert is_legal_transition(from_s, to_s) == expected_legal

            if expected_legal:
                result = transition(from_s, to_s)
                assert result == to_s
            else:
                with pytest.raises(IllegalTransitionError) as exc_info:
                    transition(from_s, to_s)
                assert exc_info.value.current == from_s
                assert exc_info.value.target == to_s


def test_cannot_skip_from_received_to_verified() -> None:
    """An action cannot skip directly from RECEIVED to VERIFIED without execution or reconciliation."""
    assert not is_legal_transition(ActionState.RECEIVED, ActionState.VERIFIED)
    with pytest.raises(IllegalTransitionError):
        transition(ActionState.RECEIVED, ActionState.VERIFIED)


@settings(max_examples=1000)
@given(
    terminal_state=st.sampled_from(list(TERMINAL_STATES)),
    target_sequence=st.lists(st.sampled_from(list(ActionState)), min_size=1, max_size=10),
)
def test_terminal_immutability(
    terminal_state: ActionState, target_sequence: list[ActionState]
) -> None:
    """From any terminal state, no sequence of transitions succeeds."""
    current = terminal_state
    for target in target_sequence:
        assert not is_legal_transition(current, target)
        with pytest.raises(IllegalTransitionError):
            transition(current, target)


@settings(max_examples=1000)
@given(
    from_state=st.sampled_from(list(ActionState)),
)
def test_retry_only_from_failed(from_state: ActionState) -> None:
    """RECEIVED is only reachable via FAILED -> RECEIVED (never from UNKNOWN, COMPENSATING, etc.)."""
    is_retry_to_received = is_legal_transition(from_state, ActionState.RECEIVED)
    if from_state == ActionState.FAILED:
        assert is_retry_to_received is True
    else:
        assert is_retry_to_received is False
        with pytest.raises(IllegalTransitionError):
            transition(from_state, ActionState.RECEIVED)


class ActionStateAuditTrailMachine(RuleBasedStateMachine):
    """Hypothesis stateful test modeling action lifecycle transitions.

    Asserts:
    1. Event list only grows (append-only).
    2. Each event's from_state strictly matches the previous event's to_state.
    3. Terminal states cannot be transitioned away from.
    """

    def __init__(self) -> None:
        super().__init__()
        self.current_state: ActionState = ActionState.RECEIVED
        self.event_trail: list[tuple[ActionState | None, ActionState]] = [
            (None, ActionState.RECEIVED)
        ]

    @rule(target_state=st.sampled_from(list(ActionState)))
    def attempt_transition(self, target_state: ActionState) -> None:
        prev_len = len(self.event_trail)
        if is_legal_transition(self.current_state, target_state):
            new_state = transition(self.current_state, target_state)
            self.event_trail.append((self.current_state, new_state))
            self.current_state = new_state

            # Invariant 1: Append-only growth
            assert len(self.event_trail) == prev_len + 1
            # Invariant 2: Chain continuity
            assert self.event_trail[-1][0] == self.event_trail[-2][1]
            assert self.event_trail[-1][1] == self.current_state
        else:
            with pytest.raises(IllegalTransitionError):
                transition(self.current_state, target_state)
            # Invariant 3: No state mutation or event emission on failure
            assert len(self.event_trail) == prev_len


TestStateAuditTrail = ActionStateAuditTrailMachine.TestCase
