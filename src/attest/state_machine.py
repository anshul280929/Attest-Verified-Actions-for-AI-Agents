"""Action state machine defining approved lifecycle transitions and invariants.

States and transitions match the Attest formal specification.
Retry is only ever allowed from FAILED, and FAILED is reached only when
the system has confirmed no downstream effect.
"""

from enum import StrEnum
from typing import Final


class ActionState(StrEnum):
    RECEIVED = "RECEIVED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class IllegalTransitionError(Exception):
    """Raised when an action state transition violates the state machine rules."""

    def __init__(
        self, current: ActionState, target: ActionState, message: str | None = None
    ) -> None:
        self.current = current
        self.target = target
        detail = message or f"Illegal transition from '{current.value}' to '{target.value}'"
        super().__init__(detail)


# Terminal states cannot transition to any other state
# (Note: FAILED is terminal when attempts are exhausted, but FAILED -> RECEIVED is legal for retries)
TERMINAL_STATES: Final[frozenset[ActionState]] = frozenset(
    {
        ActionState.VERIFIED,
        ActionState.COMPENSATED,
        ActionState.NEEDS_REVIEW,
    }
)

# Legal transition arcs as defined in Section 5.3 of the specification:
# - RECEIVED -> EXECUTED (definite success response)
# - RECEIVED -> FAILED (definite failure - no commit)
# - RECEIVED -> UNKNOWN (timeout, 5xx, reset, empty body)
# - EXECUTED -> VERIFIED (postcondition holds)
# - EXECUTED -> COMPENSATING (postcondition violated - partial write)
# - EXECUTED -> FAILED (postcondition violated - no effect)
# - EXECUTED -> UNKNOWN (verifier read path unavailable)
# - UNKNOWN -> VERIFIED (reconciled, state matches)
# - UNKNOWN -> FAILED (reconciled, no effect found)
# - UNKNOWN -> NEEDS_REVIEW (deadline exceeded)
# - FAILED -> RECEIVED (safe retry - same key, attempts left)
# - COMPENSATING -> COMPENSATED (compensation succeeded)
# - COMPENSATING -> NEEDS_REVIEW (compensation failed)
LEGAL_TRANSITIONS: Final[frozenset[tuple[ActionState, ActionState]]] = frozenset(
    {
        (ActionState.RECEIVED, ActionState.EXECUTED),
        (ActionState.RECEIVED, ActionState.FAILED),
        (ActionState.RECEIVED, ActionState.UNKNOWN),
        (ActionState.EXECUTED, ActionState.VERIFIED),
        (ActionState.EXECUTED, ActionState.COMPENSATING),
        (ActionState.EXECUTED, ActionState.FAILED),
        (ActionState.EXECUTED, ActionState.UNKNOWN),
        (ActionState.UNKNOWN, ActionState.VERIFIED),
        (ActionState.UNKNOWN, ActionState.FAILED),
        (ActionState.UNKNOWN, ActionState.NEEDS_REVIEW),
        (ActionState.FAILED, ActionState.RECEIVED),
        (ActionState.COMPENSATING, ActionState.COMPENSATED),
        (ActionState.COMPENSATING, ActionState.NEEDS_REVIEW),
    }
)

# Dictionary mapping every possible (from_state, to_state) pair to whether it is legal
TRANSITIONS: Final[dict[tuple[ActionState, ActionState], bool]] = {
    (from_s, to_s): (from_s, to_s) in LEGAL_TRANSITIONS
    for from_s in ActionState
    for to_s in ActionState
}


def is_legal_transition(current: ActionState, target: ActionState) -> bool:
    """Check whether a transition between two states is legal."""
    return TRANSITIONS.get((current, target), False)


def transition(current: ActionState, target: ActionState) -> ActionState:
    """Validate and perform a state transition.

    Raises:
        IllegalTransitionError: If the transition is not in the approved transition matrix.
    """
    if not is_legal_transition(current, target):
        raise IllegalTransitionError(current, target)
    return target
