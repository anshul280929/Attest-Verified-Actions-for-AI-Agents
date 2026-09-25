"""Pydantic schemas for action creation, retrieval, and audit events."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.attest.state_machine import ActionState


class ActionCreateRequest(BaseModel):
    """Payload for submitting an action to the Attest gateway."""

    task_id: str = Field(..., min_length=1, description="Unique identifier of the agent task run")
    step: int = Field(..., ge=1, description="Step number within the task")
    tool: str = Field(..., min_length=1, description="Name of the tool being called")
    resource_key: str = Field(
        ..., min_length=1, description="Key for resource fencing (e.g. order_id)"
    )
    args: dict[str, Any] = Field(default_factory=dict, description="Tool invocation arguments")


class ActionResponse(BaseModel):
    """Response returned upon recording or fetching an action."""

    model_config = ConfigDict(from_attributes=True)

    action_id: uuid.UUID
    idempotency_key: str
    state: ActionState | str
    verdict: str | None = None
    message: str = "action recorded"
    deduplicated: bool = False


class ActionEventResponse(BaseModel):
    """Schema representing an immutable audit event for a state transition."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_state: str | None
    to_state: str
    detail: dict[str, Any] | None = None
    at: datetime


class ActionDetailResponse(BaseModel):
    """Detailed view of an action including its full transition history."""

    model_config = ConfigDict(from_attributes=True)

    action_id: uuid.UUID
    idempotency_key: str
    task_id: str
    step: int
    tool: str
    resource_key: str
    args: dict[str, Any]
    state: ActionState | str
    verdict: str | None = None
    attempts: int = 0
    downstream_ref: str | None = None
    created_at: datetime
    updated_at: datetime
    events: list[ActionEventResponse] = Field(default_factory=list)
