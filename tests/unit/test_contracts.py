"""Unit tests for contract schema, loader, and registry."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.attest.contracts import (
    ActionContract,
    ContractLoadError,
    ContractNotFoundError,
    ContractRegistry,
    load_contracts,
)


def test_load_real_contracts() -> None:
    """Validate that real YAML contracts in contracts/ directory load without error."""
    contracts = load_contracts("contracts")
    assert "issue_refund" in contracts
    assert "cancel_order" in contracts

    refund_contract = contracts["issue_refund"]
    assert refund_contract.name == "issue_refund"
    assert refund_contract.resource_key == "{args.order_id}"
    assert refund_contract.downstream.method == "POST"
    assert refund_contract.downstream.path == "/refunds"
    assert 400 in refund_contract.downstream.definite_failure_statuses
    assert refund_contract.postcondition.read == "GET /orders/{args.order_id}"
    assert len(refund_contract.postcondition.assert_) == 3

    cancel_contract = contracts["cancel_order"]
    assert cancel_contract.name == "cancel_order"
    assert cancel_contract.postcondition.assert_ == ["body.status == 'CANCELLED'"]


def test_contract_registry_methods() -> None:
    """Test registry lookup, require, and error behavior."""
    contracts = load_contracts("contracts")
    registry = ContractRegistry(contracts)

    assert registry.get("issue_refund") is not None
    assert registry.get("unknown_tool") is None

    assert registry.require("cancel_order").name == "cancel_order"
    with pytest.raises(ContractNotFoundError) as exc_info:
        registry.require("non_existent_tool")
    assert "non_existent_tool" in str(exc_info.value)


def test_load_contracts_missing_dir(tmp_path: Path) -> None:
    """Test loading from nonexistent directory raises ContractLoadError."""
    with pytest.raises(ContractLoadError):
        load_contracts(tmp_path / "does_not_exist")


def test_load_contracts_invalid_yaml(tmp_path: Path) -> None:
    """Test loading malformed YAML file raises ContractLoadError."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("name: [unclosed list", encoding="utf-8")
    with pytest.raises(ContractLoadError):
        load_contracts(tmp_path)


def test_load_contracts_schema_violation(tmp_path: Path) -> None:
    """Test loading YAML with missing required fields raises ContractLoadError."""
    bad_file = tmp_path / "incomplete.yaml"
    bad_file.write_text("name: only_a_name\n", encoding="utf-8")
    with pytest.raises(ContractLoadError):
        load_contracts(tmp_path)


def test_contract_schema_extra_fields_forbidden() -> None:
    """Test that extra unapproved fields are rejected by the Pydantic schema."""
    with pytest.raises(ValidationError):
        ActionContract.model_validate(
            {
                "name": "test",
                "resource_key": "res-1",
                "downstream": {
                    "method": "POST",
                    "path": "/test",
                    "unexpected_field": "disallowed",
                },
                "postcondition": {
                    "read": "GET /test",
                    "assert": ["body.ok == True"],
                },
            }
        )
