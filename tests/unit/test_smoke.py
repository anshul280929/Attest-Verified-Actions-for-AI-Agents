"""Smoke tests for the Attest gateway tracer slice."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Assert health endpoint returns 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "attest-gateway"}


@pytest.mark.asyncio
async def test_post_action_tracer_slice(client: AsyncClient) -> None:
    """Plan 1 tracer: POST /v1/actions persists and returns state=RECEIVED."""
    payload = {
        "task_id": "task-test-001",
        "step": 1,
        "tool": "issue_refund",
        "resource_key": "order-12345",
        "args": {"order_id": "order-12345", "amount": 49.99},
    }

    response = await client.post("/v1/actions", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "action_id" in data
    assert data["state"] == "VERIFIED"
    assert data["verdict"] == "VERIFIED"
    assert data["deduplicated"] is False
    assert data["message"] == "action verified"
    assert len(data["idempotency_key"]) == 64
