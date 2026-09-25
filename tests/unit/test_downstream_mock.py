"""Unit tests for downstream mock service and deterministic fault injection."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.downstream_mock.app import app as mock_app
from src.downstream_mock.config import mock_settings
from src.downstream_mock.store import store


@pytest_asyncio.fixture
async def mock_client() -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing an async test client for the downstream mock."""
    mock_settings.timeout_delay_seconds = 0.05  # speed up timeout tests
    store.reset()
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://mock-test") as client:
        yield client
    store.reset()


@pytest.mark.asyncio
async def test_mock_health(mock_client: AsyncClient) -> None:
    """Health check endpoint returns ok."""
    resp = await mock_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "downstream-mock"}


@pytest.mark.asyncio
async def test_profile_none_clean_refund(mock_client: AsyncClient) -> None:
    """Under 'none' profile, refund succeeds and updates order state."""
    payload = {"order_id": "order-12345", "amount": 25.0, "reason": "damaged_goods"}
    resp = await mock_client.post(
        "/refunds",
        json=payload,
        headers={"X-Fault-Profile": "none", "Idempotency-Key": "key-none-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 25.0
    assert data["status"] == "COMPLETED"

    # Verify read path
    order_resp = await mock_client.get("/orders/order-12345")
    assert order_resp.status_code == 200
    order_data = order_resp.json()
    assert order_data["refunded_amount"] == 25.0
    assert order_data["status"] == "PARTIALLY_REFUNDED"


@pytest.mark.asyncio
async def test_profile_timeout_after_commit(mock_client: AsyncClient) -> None:
    """Under 'timeout_after_commit', order state is modified even though delay occurs."""
    payload = {"order_id": "order-12345", "amount": 50.0, "reason": "delay_test"}
    resp = await mock_client.post(
        "/refunds",
        json=payload,
        headers={"X-Fault-Profile": "timeout_after_commit", "Idempotency-Key": "key-timeout-1"},
    )
    assert resp.status_code == 200
    # State was committed in store
    order_resp = await mock_client.get("/orders/order-12345")
    assert order_resp.json()["refunded_amount"] == 50.0


@pytest.mark.asyncio
async def test_profile_empty_200(mock_client: AsyncClient) -> None:
    """Under 'empty_200', response body is empty with status 200."""
    payload = {"order_id": "order-12345", "amount": 30.0, "reason": "empty_test"}
    resp = await mock_client.post(
        "/refunds",
        json=payload,
        headers={"X-Fault-Profile": "empty_200", "X-Fault-Seed": "123"},
    )
    assert resp.status_code == 200
    assert resp.text == ""


@pytest.mark.asyncio
async def test_profile_duplicate_delivery(mock_client: AsyncClient) -> None:
    """Under 'duplicate_delivery', refund is applied twice from one request."""
    payload = {"order_id": "order-12345", "amount": 20.0, "reason": "dup_test"}
    resp = await mock_client.post(
        "/refunds",
        json=payload,
        headers={"X-Fault-Profile": "duplicate_delivery", "Idempotency-Key": "key-dup-1"},
    )
    assert resp.status_code == 200

    order_resp = await mock_client.get("/orders/order-12345")
    order_data = order_resp.json()
    # Amount deducted is 20.0 * 2 = 40.0
    assert order_data["refunded_amount"] == 40.0
    # Two refund records created
    assert len(store.refunds) == 2


@pytest.mark.asyncio
async def test_profile_partial_write(mock_client: AsyncClient) -> None:
    """Under 'partial_write', refund record exists but order refunded_amount remains 0."""
    payload = {"order_id": "order-12345", "amount": 35.0, "reason": "partial_test"}
    resp = await mock_client.post(
        "/refunds",
        json=payload,
        headers={"X-Fault-Profile": "partial_write", "Idempotency-Key": "key-partial-1"},
    )
    assert resp.status_code == 200
    refund_id = resp.json()["refund_id"]

    # Refund was recorded in store
    assert refund_id in store.refunds

    # BUT order state was NOT updated (simulating incomplete write)
    order_resp = await mock_client.get("/orders/order-12345")
    assert order_resp.json()["refunded_amount"] == 0.0
    assert order_resp.json()["status"] == "PAID"


@pytest.mark.asyncio
async def test_seed_determinism(mock_client: AsyncClient) -> None:
    """The same seed produces identical behavior on empty_200 coin tosses."""
    results_run_1 = []
    for _ in range(5):
        store.reset()
        await mock_client.post(
            "/refunds",
            json={"order_id": "order-12345", "amount": 10.0, "reason": "seed_test"},
            headers={"X-Fault-Profile": "empty_200", "X-Fault-Seed": "99999"},
        )
        results_run_1.append(store.orders["order-12345"].refunded_amount)

    results_run_2 = []
    for _ in range(5):
        store.reset()
        await mock_client.post(
            "/refunds",
            json={"order_id": "order-12345", "amount": 10.0, "reason": "seed_test"},
            headers={"X-Fault-Profile": "empty_200", "X-Fault-Seed": "99999"},
        )
        results_run_2.append(store.orders["order-12345"].refunded_amount)

    assert results_run_1 == results_run_2
