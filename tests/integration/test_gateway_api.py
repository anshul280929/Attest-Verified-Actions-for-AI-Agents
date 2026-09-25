"""Integration tests for Gateway API endpoints and Ledger Guard."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.attest.app import app
from src.attest.database import get_db


@pytest.mark.asyncio
async def test_get_action_with_events_integration(gateway_client: AsyncClient) -> None:
    """GATE-01 & GATE-02: Action ingestion followed by full audit history retrieval."""
    task_id = f"task-get-{uuid.uuid4().hex[:6]}"
    payload = {
        "task_id": task_id,
        "step": 1,
        "tool": "issue_refund",
        "resource_key": "order-get-e2e",
        "args": {"order_id": "order-get-e2e", "amount": 80.0},
    }

    create_resp = await gateway_client.post("/v1/actions", json=payload)
    assert create_resp.status_code == 200
    action_id = create_resp.json()["action_id"]

    get_resp = await gateway_client.get(f"/v1/actions/{action_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["action_id"] == action_id
    assert data["state"] == "RECEIVED"
    assert len(data["events"]) == 1
    assert data["events"][0]["to_state"] == "RECEIVED"
    assert data["events"][0]["from_state"] is None


@pytest.mark.asyncio
async def test_ledger_guard_blocks_downstream_execution() -> None:
    """GATE-03: If database ledger write fails, gateway returns 503 and blocks execution."""

    async def failing_get_db() -> AsyncGenerator[None, None]:
        raise OperationalError(
            "Database unreachable", params=None, orig=Exception("DB unavailable")
        )
        yield

    app.dependency_overrides[get_db] = failing_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://gateway.attest.local") as client:
        resp = await client.post(
            "/v1/actions",
            json={
                "task_id": "task-blocked",
                "step": 1,
                "tool": "issue_refund",
                "resource_key": "order-blocked",
                "args": {"order_id": "order-blocked"},
            },
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["detail"]["error"] == "ledger_unavailable"
        assert "execution blocked" in data["detail"]["message"]

    app.dependency_overrides.clear()
