"""Unit tests for URL template engine and read spec parser."""

import pytest

from src.attest.contracts.template import (
    TemplateSubstitutionError,
    parse_read_spec,
    substitute_path,
)


def test_substitute_path_basic_and_nested() -> None:
    """Test substituting top-level and dot-notation variables."""
    args = {
        "order_id": "ord-12345",
        "nested": {"id": "sub-99"},
    }

    path = substitute_path("/orders/{args.order_id}", args)
    assert path == "/orders/ord-12345"

    path_nested = substitute_path("/items/{args.nested.id}", args)
    assert path_nested == "/items/sub-99"


def test_substitute_path_downstream_ref_and_resource_key() -> None:
    """Test substituting downstream_ref and resource_key variables."""
    path = substitute_path(
        "/refunds/{downstream_ref}/reverse",
        args={},
        downstream_ref="ref-abc123",
        resource_key="ord-123",
    )
    assert path == "/refunds/ref-abc123/reverse"

    path_res = substitute_path(
        "/resources/{resource_key}/check",
        args={},
        resource_key="ord-123",
    )
    assert path_res == "/resources/ord-123/check"


def test_substitute_path_missing_variable_raises() -> None:
    """Test that missing required variables raise TemplateSubstitutionError."""
    with pytest.raises(TemplateSubstitutionError):
        substitute_path("/orders/{args.missing_key}", {"other": "val"})

    with pytest.raises(TemplateSubstitutionError):
        substitute_path("/refunds/{downstream_ref}/reverse", {})


def test_parse_read_spec() -> None:
    """Test parsing HTTP method and path from read spec."""
    method, path = parse_read_spec("GET /orders/{args.order_id}")
    assert method == "GET"
    assert path == "/orders/{args.order_id}"

    method2, path2 = parse_read_spec("POST /verify")
    assert method2 == "POST"
    assert path2 == "/verify"

    # Default to GET if method omitted
    method3, path3 = parse_read_spec("/orders/123")
    assert method3 == "GET"
    assert path3 == "/orders/123"
