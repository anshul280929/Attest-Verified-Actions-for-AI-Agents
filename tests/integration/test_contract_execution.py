"""End-to-end integration tests across all five fault profiles and contracts.

Enforces:
- CONT-01: YAML contract loading and validation
- CONT-02: Downstream execution with Idempotency-Key
- CONT-03: Sandboxed assertion evaluation
- CONT-05: State verification (VERIFIED / FAILED / COMPENSATING)
- CONT-06: Ambiguous responses -> UNKNOWN with outbox
- CONT-07: Definite failures -> FAILED without retry unless confirmed safe
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.attest.models.action import Action, Outbox
from src.downstream_mock.store import store


@pytest.mark.asyncio
async def test_e2e_happy_path_refund(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """Happy path: clean execution and independent verification yields VERIFIED."""
    order_id = "order-12345"
    payload = {
        "task_id": "task-happy-refund",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": order_id,
        "args": {"order_id": order_id, "amount": 50.0},
    }

    resp = await gateway_client.post("/v1/actions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "VERIFIED"
    assert data["verdict"] == "VERIFIED"
    assert data["deduplicated"] is False
    assert data["message"] == "action verified"

    # Verify audit trail and DB state
    action_id = uuid.UUID(data["action_id"])
    stmt = select(Action).where(Action.id == action_id)
    result = await integration_session.execute(stmt)
    action_row = result.scalar_one_or_none()
    assert action_row is not None
    assert action_row.state == "VERIFIED"

    # Verify downstream store actually recorded the change
    order = store.orders[order_id]
    assert order.refunded_amount == 50.0


@pytest.mark.asyncio
async def test_e2e_happy_path_cancellation(gateway_client: AsyncClient) -> None:
    """Happy path: order cancellation verified independently."""
    order_id = "order-67890"
    payload = {
        "task_id": "task-happy-cancel",
        "step": 1,
        "tool": "cancel_order",
        "resource_key": order_id,
        "args": {"order_id": order_id},
    }

    resp = await gateway_client.post("/v1/actions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "VERIFIED"
    assert data["verdict"] == "VERIFIED"
    assert store.orders[order_id].status == "CANCELLED"


@pytest.mark.asyncio
async def test_e2e_timeout_after_commit_becomes_unknown(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """CONT-06: Timeout after commit becomes UNKNOWN with outbox reconciliation entry."""
    order_id = "order-12345"
    payload = {
        "task_id": "task-timeout-1",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": order_id,
        "args": {"order_id": order_id, "amount": 25.0},
    }

    resp = await gateway_client.post(
        "/v1/actions",
        json=payload,
        headers={"X-Fault-Profile": "timeout_after_commit"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "UNKNOWN"
    assert data["verdict"] == "UNKNOWN"
    assert "pending confirmation" in data["message"]

    action_id = uuid.UUID(data["action_id"])
    outbox_stmt = select(Outbox).where(Outbox.action_id == action_id)
    outbox_res = await integration_session.execute(outbox_stmt)
    outbox_row = outbox_res.scalar_one_or_none()
    assert outbox_row is not None
    assert outbox_row.kind == "reconcile"


@pytest.mark.asyncio
async def test_e2e_empty_200_becomes_unknown(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """CONT-06: Empty 200 body is ambiguous and becomes UNKNOWN with outbox entry."""
    order_id = "order-12345"
    payload = {
        "task_id": "task-empty-200",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": order_id,
        "args": {"order_id": order_id, "amount": 20.0},
    }

    resp = await gateway_client.post(
        "/v1/actions",
        json=payload,
        headers={"X-Fault-Profile": "empty_200"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "UNKNOWN"
    assert data["verdict"] == "UNKNOWN"

    action_id = uuid.UUID(data["action_id"])
    outbox_stmt = select(Outbox).where(Outbox.action_id == action_id)
    outbox_res = await integration_session.execute(outbox_stmt)
    outbox_row = outbox_res.scalar_one_or_none()
    assert outbox_row is not None
    assert outbox_row.kind == "reconcile"


@pytest.mark.asyncio
async def test_e2e_definite_failure_404(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """CONT-07: Definite 404 from downstream transitions to FAILED with no outbox."""
    payload = {
        "task_id": "task-fail-404",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": "non-existent-order",
        "args": {"order_id": "non-existent-order", "amount": 50.0},
    }

    resp = await gateway_client.post("/v1/actions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "FAILED"
    assert data["verdict"] == "FAILED"

    # Confirm no outbox entry was inserted
    action_id = uuid.UUID(data["action_id"])
    outbox_stmt = select(Outbox).where(Outbox.action_id == action_id)
    outbox_res = await integration_session.execute(outbox_stmt)
    assert outbox_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_e2e_partial_write_becomes_compensating(
    gateway_client: AsyncClient, integration_session: AsyncSession
) -> None:
    """CONT-05: Partial write detected on verification read transitions to COMPENSATING."""
    order_id = "order-12345"
    payload = {
        "task_id": "task-partial-write",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": order_id,
        "args": {"order_id": order_id, "amount": 40.0},
    }

    resp = await gateway_client.post(
        "/v1/actions",
        json=payload,
        headers={"X-Fault-Profile": "partial_write"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["state"] == "COMPENSATING"
    assert data["verdict"] == "FAILED"
    assert "compensation" in data["message"].lower()

    action_id = uuid.UUID(data["action_id"])
    outbox_stmt = select(Outbox).where(Outbox.action_id == action_id)
    outbox_res = await integration_session.execute(outbox_stmt)
    outbox_row = outbox_res.scalar_one_or_none()
    assert outbox_row is not None
    assert outbox_row.kind == "compensate"


@pytest.mark.asyncio
async def test_e2e_duplicate_delivery_detected_by_assertion(gateway_client: AsyncClient) -> None:
    """CONT-05: Duplicate delivery profile causes refund count > 1, caught by contract assert."""
    order_id = "order-12345"
    payload = {
        "task_id": "task-dup-delivery",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": order_id,
        "args": {"order_id": order_id, "amount": 10.0},
    }

    resp = await gateway_client.post(
        "/v1/actions",
        json=payload,
        headers={"X-Fault-Profile": "duplicate_delivery"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Double delivery triggers compensation due to partial/corrupted multi-write
    assert data["state"] in {"COMPENSATING", "FAILED"}
    assert data["verdict"] == "FAILED"
    # Never falsely claimed VERIFIED!
    assert data["state"] != "VERIFIED"


@pytest.mark.asyncio
async def test_e2e_unknown_tool_returns_422(gateway_client: AsyncClient) -> None:
    """GATE-01: Ingestion rejects uncontracted tool names with 422."""
    payload = {
        "task_id": "task-unknown-tool",
        "step": 1,
        "tool": "unregistered_tool_name",
        "resource_key": "res-1",
        "args": {"key": "val"},
    }

    resp = await gateway_client.post("/v1/actions", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert "unknown_tool" in str(data)
