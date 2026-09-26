"""Pydantic v2 schemas defining declarative action contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DownstreamConfig(BaseModel):
    """Specification of the downstream mutation endpoint."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(..., min_length=1, description="HTTP method (e.g. POST, PUT)")
    path: str = Field(..., min_length=1, description="Path template for the mutation")
    idempotency_header: str = Field(
        default="Idempotency-Key", description="Header name for idempotency forwarding"
    )
    timeout_ms: Annotated[int, Field(gt=0, description="Downstream call timeout in milliseconds")] = (
        2000
    )
    definite_failure_statuses: list[int] = Field(
        default_factory=list,
        description="HTTP status codes indicating definite no-commit failures",
    )


class PostconditionConfig(BaseModel):
    """Specification of the independent verification read and state assertions."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    read: str = Field(..., min_length=1, description="Read specification (e.g. 'GET /orders/{args.order_id}')")
    assert_: list[str] = Field(
        ...,
        alias="assert",
        min_length=1,
        description="List of boolean expression assertions evaluated against the read response",
    )


class CompensationConfig(BaseModel):
    """Specification of compensating action if verification detects partial write."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(..., min_length=1, description="HTTP method for compensation")
    path: str = Field(..., min_length=1, description="Path template for compensation")


class ReconcileConfig(BaseModel):
    """Specification of reconciliation polling retry schedule and deadline."""

    model_config = ConfigDict(extra="forbid")

    backoff_seconds: list[int] = Field(
        default_factory=lambda: [1, 2, 4, 8, 16],
        description="Exponential backoff intervals in seconds",
    )
    deadline_seconds: Annotated[int, Field(gt=0, description="Reconciliation deadline in seconds")] = (
        60
    )


class ActionContract(BaseModel):
    """Top-level contract declaring execution, verification, and reconciliation rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(..., min_length=1, description="Action/tool name matching the contract")
    resource_key: str = Field(
        ..., min_length=1, description="Template string for resource fencing identifier"
    )
    downstream: DownstreamConfig
    postcondition: PostconditionConfig
    compensation: CompensationConfig | None = None
    reconcile: ReconcileConfig = Field(default_factory=ReconcileConfig)
