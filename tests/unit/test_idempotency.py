"""Unit and property tests for idempotency key derivation and deduplication.

Validates:
- LEDG-02: Deterministic key generation from (task_id, step, tool, args)
- LEDG-03: Deduplication returning existing record without re-executing
"""

from typing import Any

import pytest
from httpx import AsyncClient

from src.attest.idempotency import canonical_json, derive_key


def test_canonical_json_key_order_independence() -> None:
    """Dictionaries with different key insertion orders produce identical canonical JSON."""
    dict_a = {"b": 1, "a": 2, "z": {"nested_b": True, "nested_a": "hello"}}
    dict_b = {"a": 2, "z": {"nested_a": "hello", "nested_b": True}, "b": 1}

    assert canonical_json(dict_a) == canonical_json(dict_b)


def test_canonical_json_nested_objects_and_nulls() -> None:
    """Nested structures, null values, lists, and booleans serialize deterministically."""
    data: dict[str, Any] = {
        "items": [{"id": 2, "name": "B"}, {"id": 1, "name": "A"}],
        "nullable": None,
        "flag": False,
        "empty_list": [],
        "empty_dict": {},
    }
    canonical = canonical_json(data)
    assert '"empty_dict":{}' in canonical
    assert '"empty_list":[]' in canonical
    assert '"flag":false' in canonical
    assert '"nullable":null' in canonical


def test_derive_key_format_and_determinism() -> None:
    """Keys are 64-char hex strings and deterministic across identical inputs."""
    task_id = "task-alpha"
    step = 3
    tool = "issue_refund"
    args1 = {"order_id": "ord-1", "amount": 99.5}
    args2 = {"amount": 99.5, "order_id": "ord-1"}

    key1 = derive_key(task_id, step, tool, args1)
    key2 = derive_key(task_id, step, tool, args2)

    assert len(key1) == 64
    assert int(key1, 16) > 0  # valid hex
    assert key1 == key2


def test_derive_key_sensitivity_to_variations() -> None:
    """Any variation in task, step, tool, or arguments produces a distinct key."""
    base = ("task-1", 1, "toolA", {"x": 10})
    base_key = derive_key(*base)

    # Different step
    assert derive_key("task-1", 2, "toolA", {"x": 10}) != base_key
    # Different task
    assert derive_key("task-2", 1, "toolA", {"x": 10}) != base_key
    # Different tool
    assert derive_key("task-1", 1, "toolB", {"x": 10}) != base_key
    # Different args
    assert derive_key("task-1", 1, "toolA", {"x": 11}) != base_key


@pytest.mark.asyncio
async def test_api_deduplication(client: AsyncClient) -> None:
    """POSTing identical action payload twice returns original action_id with deduplicated=true."""
    payload = {
        "task_id": "task-dedup-100",
        "step": 1,
        "tool": "cancel_order",
        "resource_key": "order-67890",
        "args": {"order_id": "order-67890", "reason": "user_cancelled"},
    }

    # First submission
    resp1 = await client.post("/v1/actions", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["deduplicated"] is False
    action_id_1 = data1["action_id"]
    assert data1["state"] == "VERIFIED"

    # Second submission (identical)
    resp2 = await client.post("/v1/actions", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["deduplicated"] is True
    assert data2["action_id"] == action_id_1
    assert data2["idempotency_key"] == data1["idempotency_key"]
    assert data2["state"] == "VERIFIED"

    # Verify action details and audit trail: exactly 1 execution lifecycle occurred
    detail_resp = await client.get(f"/v1/actions/{action_id_1}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert len(detail_data["events"]) == 3
    assert detail_data["events"][0]["to_state"] == "RECEIVED"
    assert detail_data["events"][1]["to_state"] == "EXECUTED"
    assert detail_data["events"][2]["to_state"] == "VERIFIED"
