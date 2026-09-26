"""Unit tests for independent state verifier."""

import httpx
import pytest

from src.attest.contracts import ActionContract, load_contracts
from src.attest.verifier import verify_postcondition


@pytest.fixture
def refund_contract() -> ActionContract:
    contracts = load_contracts("contracts")
    return contracts["issue_refund"]


@pytest.fixture
def cancel_contract() -> ActionContract:
    contracts = load_contracts("contracts")
    return contracts["cancel_order"]


@pytest.mark.asyncio
async def test_verifier_verified_verdict(refund_contract: ActionContract) -> None:
    """Test when postcondition holds, verdict is VERIFIED."""
    read_response = {
        "order_id": "ord-123",
        "status": "PAID",
        "refunded_amount": 50.0,
        "refund": {
            "status": "processed",
            "amount": 50.0,
            "count": 1,
        },
    }
    handler = httpx.MockTransport(
        lambda request: httpx.Response(status_code=200, json=read_response)
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await verify_postcondition(
            contract=refund_contract,
            args={"order_id": "ord-123", "amount": 50.0},
            client=client,
        )

    assert res.verdict == "VERIFIED"
    assert res.failing_assertion is None


@pytest.mark.asyncio
async def test_verifier_failed_verdict(cancel_contract: ActionContract) -> None:
    """Test when postcondition is violated with no effect, verdict is FAILED."""
    read_response = {
        "order_id": "ord-123",
        "status": "PAID",  # Expecting CANCELLED
    }
    handler = httpx.MockTransport(
        lambda request: httpx.Response(status_code=200, json=read_response)
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await verify_postcondition(
            contract=cancel_contract,
            args={"order_id": "ord-123"},
            client=client,
        )

    assert res.verdict == "FAILED"
    assert res.failing_assertion == "body.status == 'CANCELLED'"


@pytest.mark.asyncio
async def test_verifier_compensating_verdict(refund_contract: ActionContract) -> None:
    """Test partial write detection triggers COMPENSATING verdict."""
    # Refund summary count is 1, but status did not complete (e.g. partial write)
    read_response = {
        "order_id": "ord-123",
        "status": "PAID",
        "refunded_amount": 0.0,
        "refund": {
            "status": "none",
            "amount": 0.0,
            "count": 1,  # Refund created, but order not updated
        },
        "refunds": [{"refund_id": "ref-1", "amount": 50.0}],
    }
    handler = httpx.MockTransport(
        lambda request: httpx.Response(status_code=200, json=read_response)
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await verify_postcondition(
            contract=refund_contract,
            args={"order_id": "ord-123", "amount": 50.0},
            client=client,
        )

    assert res.verdict == "COMPENSATING"
    assert res.failing_assertion is not None


@pytest.mark.asyncio
async def test_verifier_read_path_unavailable_returns_unknown(
    refund_contract: ActionContract,
) -> None:
    """Test read path 500 returns UNKNOWN verdict (never assume verified)."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(status_code=500, text="Read path error")
    )
    async with httpx.AsyncClient(transport=handler, base_url="http://mock") as client:
        res = await verify_postcondition(
            contract=refund_contract,
            args={"order_id": "ord-123", "amount": 50.0},
            client=client,
        )

    assert res.verdict == "UNKNOWN"
    assert "error" in res.detail
