"""Unit tests for Gateway API endpoints, validation, and Ledger Guard.

Validates:
- GATE-01: Ingestion API accepting structured tool actions
- GATE-02: Action state and audit trail retrieval
- GATE-03: Ledger Guard refusing tool execution when ledger write fails
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.attest.app import app
from src.attest.database import get_db


@pytest.mark.asyncio
async def test_get_action_endpoint(client: AsyncClient) -> None:
    """GET /v1/actions/{id} returns action details and ordered events."""
    payload = {
        "task_id": "task-api-1",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": "order-12345",
        "args": {"order_id": "order-12345", "amount": 20.0},
    }
    create_resp = await client.post("/v1/actions", json=payload)
    assert create_resp.status_code == 200
    action_id = create_resp.json()["action_id"]

    get_resp = await client.get(f"/v1/actions/{action_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["action_id"] == action_id
    assert data["tool"] == "issue_refund"
    assert data["resource_key"] == "order-12345"
    assert data["state"] == "VERIFIED"
    assert data["verdict"] == "VERIFIED"
    assert len(data["events"]) == 3
    assert data["events"][0]["to_state"] == "RECEIVED"
    assert data["events"][1]["to_state"] == "EXECUTED"
    assert data["events"][2]["to_state"] == "VERIFIED"


@pytest.mark.asyncio
async def test_get_nonexistent_action_returns_404(client: AsyncClient) -> None:
    """GET /v1/actions/{unknown_id} returns 404."""
    unknown_id = uuid.uuid4()
    resp = await client.get(f"/v1/actions/{unknown_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_action_validation_errors(client: AsyncClient) -> None:
    """Validation rejects missing fields, step < 1, or empty strings."""
    # Missing tool
    resp1 = await client.post(
        "/v1/actions", json={"task_id": "t1", "step": 1, "resource_key": "k1"}
    )
    assert resp1.status_code == 422

    # Step < 1
    resp2 = await client.post(
        "/v1/actions",
        json={"task_id": "t1", "step": 0, "tool": "refund", "resource_key": "k1"},
    )
    assert resp2.status_code == 422

    # Empty task_id
    resp3 = await client.post(
        "/v1/actions",
        json={"task_id": "", "step": 1, "tool": "refund", "resource_key": "k1"},
    )
    assert resp3.status_code == 422


@pytest.mark.asyncio
async def test_ledger_guard_blocks_on_db_failure() -> None:
    """GATE-03: When database write fails, gateway returns 503 and blocks execution."""

    async def broken_get_db() -> AsyncGenerator[None, None]:
        # Simulate database connection outage
        raise OperationalError("Connection refused", params=None, orig=Exception("DB down"))
        yield

    app.dependency_overrides[get_db] = broken_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "task_id": "task-fail-db",
            "step": 1,
            "tool": "cancel_order",
            "resource_key": "order-fail-db",
            "args": {"order_id": "order-fail-db"},
        }
        resp = await ac.post("/v1/actions", json=payload)
        assert resp.status_code == 503
        data = resp.json()
        assert data["detail"]["error"] == "ledger_unavailable"
        assert "execution blocked" in data["detail"]["message"]

    app.dependency_overrides.clear()
