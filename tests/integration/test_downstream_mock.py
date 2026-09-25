"""Integration tests for downstream mock service under fault injection.

Validates:
- CONT-04: Deterministic chaos profiles for timeouts, partial writes, and empty bodies
"""

import pytest
from httpx import AsyncClient

from src.downstream_mock.config import mock_settings
from src.downstream_mock.store import store


@pytest.mark.asyncio
async def test_downstream_fault_profiles_e2e(downstream_client: AsyncClient) -> None:
    """Verify all 5 fault profiles execute according to contract over HTTP."""
    mock_settings.timeout_delay_seconds = 0.05
    store.reset()

    # 1. Profile NONE
    resp_none = await downstream_client.post(
        "/refunds",
        json={"order_id": "order-12345", "amount": 10.0, "reason": "none_test"},
        headers={"X-Fault-Profile": "none", "Idempotency-Key": "e2e-none"},
    )
    assert resp_none.status_code == 200
    assert resp_none.json()["status"] == "COMPLETED"

    # 2. Profile TIMEOUT_AFTER_COMMIT
    resp_timeout = await downstream_client.post(
        "/refunds",
        json={"order_id": "order-12345", "amount": 15.0, "reason": "timeout_test"},
        headers={"X-Fault-Profile": "timeout_after_commit", "Idempotency-Key": "e2e-timeout"},
    )
    assert resp_timeout.status_code == 200
    # State was committed despite latency
    order_check = await downstream_client.get("/orders/order-12345")
    assert order_check.json()["refunded_amount"] == 25.0

    # 3. Profile EMPTY_200
    resp_empty = await downstream_client.post(
        "/refunds",
        json={"order_id": "order-12345", "amount": 10.0, "reason": "empty_test"},
        headers={"X-Fault-Profile": "empty_200"},
    )
    assert resp_empty.status_code == 200
    assert resp_empty.text == ""

    # 4. Profile DUPLICATE_DELIVERY
    resp_dup = await downstream_client.post(
        "/refunds",
        json={"order_id": "order-67890", "amount": 20.0, "reason": "dup_test"},
        headers={"X-Fault-Profile": "duplicate_delivery"},
    )
    assert resp_dup.status_code == 200
    # 20.0 * 2 = 40.0
    order_dup = await downstream_client.get("/orders/order-67890")
    assert order_dup.json()["refunded_amount"] == 40.0

    # 5. Profile PARTIAL_WRITE
    resp_part = await downstream_client.post(
        "/refunds",
        json={"order_id": "order-67890", "amount": 30.0, "reason": "partial_test"},
        headers={"X-Fault-Profile": "partial_write"},
    )
    assert resp_part.status_code == 200
    # Order status not updated despite 200
    order_part = await downstream_client.get("/orders/order-67890")
    assert order_part.json()["refunded_amount"] == 40.0  # unchanged from dup test


@pytest.mark.asyncio
async def test_seed_determinism_e2e(downstream_client: AsyncClient) -> None:
    """Verify seeded chaos produces reproducible outcomes across runs."""
    seed_val = "88442"
    outcomes_1 = []
    for _ in range(4):
        store.reset()
        await downstream_client.post(
            "/refunds",
            json={"order_id": "order-12345", "amount": 10.0, "reason": "test"},
            headers={"X-Fault-Profile": "empty_200", "X-Fault-Seed": seed_val},
        )
        outcomes_1.append(store.orders["order-12345"].refunded_amount)

    outcomes_2 = []
    for _ in range(4):
        store.reset()
        await downstream_client.post(
            "/refunds",
            json={"order_id": "order-12345", "amount": 10.0, "reason": "test"},
            headers={"X-Fault-Profile": "empty_200", "X-Fault-Seed": seed_val},
        )
        outcomes_2.append(store.orders["order-12345"].refunded_amount)

    assert outcomes_1 == outcomes_2
