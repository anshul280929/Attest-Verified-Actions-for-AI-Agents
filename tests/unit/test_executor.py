"""Unit tests for downstream executor and response classification."""

import httpx
import pytest

from src.attest.contracts import ActionContract, load_contracts
from src.attest.executor import execute_contract


@pytest.fixture
def refund_contract() -> ActionContract:
    contracts = load_contracts("contracts")
    return contracts["issue_refund"]


@pytest.mark.asyncio
async def test_execute_contract_definite_success(refund_contract: ActionContract) -> None:
    """Test 200 response with JSON content is classified as definite_success."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=200,
            json={"refund_id": "ref-100", "order_id": "ord-1", "amount": 50.0},
        )
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await execute_contract(
            contract=refund_contract,
            args={"order_id": "ord-1", "amount": 50.0},
            idempotency_key="key-123",
            client=client,
        )

    assert res.classification == "definite_success"
    assert res.status_code == 200
    assert res.downstream_ref == "ref-100"
    assert res.body is not None


@pytest.mark.asyncio
async def test_execute_contract_definite_failure(refund_contract: ActionContract) -> None:
    """Test 400 response listed in definite_failure_statuses is classified as definite_failure."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=400,
            json={"detail": "Order cannot be refunded"},
        )
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await execute_contract(
            contract=refund_contract,
            args={"order_id": "ord-1", "amount": 50.0},
            idempotency_key="key-123",
            client=client,
        )

    assert res.classification == "definite_failure"
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_execute_contract_empty_200_is_ambiguous(refund_contract: ActionContract) -> None:
    """Test 200 with empty body is classified as ambiguous."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(status_code=200, content=b"")
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await execute_contract(
            contract=refund_contract,
            args={"order_id": "ord-1", "amount": 50.0},
            idempotency_key="key-123",
            client=client,
        )

    assert res.classification == "ambiguous"
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_execute_contract_500_is_ambiguous(refund_contract: ActionContract) -> None:
    """Test 500 server error is classified as ambiguous (may have committed)."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=500,
            text="Internal Server Error",
        )
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await execute_contract(
            contract=refund_contract,
            args={"order_id": "ord-1", "amount": 50.0},
            idempotency_key="key-123",
            client=client,
        )

    assert res.classification == "ambiguous"
    assert res.status_code == 500


@pytest.mark.asyncio
async def test_execute_contract_timeout_is_ambiguous(refund_contract: ActionContract) -> None:
    """Test client timeout exception is classified as ambiguous."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout exceeded", request=request)

    handler = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await execute_contract(
            contract=refund_contract,
            args={"order_id": "ord-1", "amount": 50.0},
            idempotency_key="key-123",
            client=client,
        )

    assert res.classification == "ambiguous"
    assert "timeout" in str(res.error_detail).lower()
