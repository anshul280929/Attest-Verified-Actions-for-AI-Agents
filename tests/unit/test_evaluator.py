"""Unit tests for sandboxed AST expression evaluator."""

import pytest

from src.attest.contracts.evaluator import (
    EvaluationError,
    UnsafeExpressionError,
    evaluate,
    evaluate_postcondition,
)


def test_evaluator_basic_comparisons() -> None:
    """Test basic arithmetic and comparison evaluation."""
    assert evaluate("1 == 1", {}) is True
    assert evaluate("1 != 2", {}) is True
    assert evaluate("10 > 5", {}) is True
    assert evaluate("5 <= 5", {}) is True
    assert evaluate("2 + 3 == 5", {}) is True
    assert evaluate("10 - 4 == 6", {}) is True


def test_evaluator_dict_and_attribute_navigation() -> None:
    """Test dot-syntax navigation over dictionary contexts."""
    context = {
        "body": {
            "refund": {
                "status": "processed",
                "amount": 50.0,
                "count": 1,
            },
            "status": "PAID",
        },
        "args": {
            "order_id": "order-12345",
            "amount": 50.0,
        },
    }

    assert evaluate("body.refund.status == 'processed'", context) is True
    assert evaluate("body.refund.amount == args.amount", context) is True
    assert evaluate("body.refund.count == 1", context) is True
    assert evaluate("body.status == 'PAID'", context) is True
    assert evaluate("body.refund.amount > 0", context) is True
    assert evaluate("body.refund.status != 'none'", context) is True


def test_evaluator_boolean_logic() -> None:
    """Test and, or, not operators."""
    context = {"a": True, "b": False, "val": 10}
    assert evaluate("a and not b", context) is True
    assert evaluate("b or a", context) is True
    assert evaluate("val > 5 and val < 20", context) is True
    assert evaluate("not (val < 5)", context) is True


def test_evaluator_collections_and_membership() -> None:
    """Test lists and 'in' membership operators."""
    context = {"roles": ["admin", "editor"], "target": "admin"}
    assert evaluate("target in roles", context) is True
    assert evaluate("'viewer' not in roles", context) is True


def test_evaluator_missing_variable_raises() -> None:
    """Test lookup of non-existent variable raises EvaluationError."""
    with pytest.raises(EvaluationError):
        evaluate("non_existent_var == 1", {})


def test_evaluator_rejects_function_calls() -> None:
    """Verify function calls are strictly forbidden."""
    with pytest.raises(UnsafeExpressionError):
        evaluate("len([1, 2, 3]) == 3", {})


def test_evaluator_rejects_imports_and_builtins() -> None:
    """Verify dangerous Python escape patterns are blocked at AST validation."""
    dangerous = [
        "__import__('os').system('echo pwned')",
        "exec('a = 1')",
        "eval('1 + 1')",
        "open('/etc/passwd')",
        "().__class__.__bases__[0].__subclasses__()",
        "lambda x: x",
        "[x for x in [1, 2, 3]]",
        "f'{1 + 1}'",
    ]
    for expr in dangerous:
        with pytest.raises(UnsafeExpressionError):
            evaluate(expr, {})


def test_evaluator_max_depth_exceeded() -> None:
    """Verify deeply nested AST expressions are rejected."""
    nested = "1"
    for _ in range(25):
        nested = f"({nested} + 1)"
    with pytest.raises(UnsafeExpressionError):
        evaluate(nested, {})


def test_evaluate_postcondition_all_passing() -> None:
    """Test evaluate_postcondition when all assertions pass."""
    body = {
        "refund": {"status": "processed", "amount": 25.0, "count": 1},
        "status": "REFUNDED",
    }
    args = {"amount": 25.0, "order_id": "ord-1"}
    assertions = [
        "body.refund.status == 'processed'",
        "body.refund.amount == args.amount",
        "body.refund.count == 1",
    ]

    passed, failed_expr = evaluate_postcondition(assertions, body, args)
    assert passed is True
    assert failed_expr is None


def test_evaluate_postcondition_one_failing() -> None:
    """Test evaluate_postcondition returns the first failing expression."""
    body = {
        "refund": {"status": "processed", "amount": 50.0, "count": 2},  # count != 1
    }
    args = {"amount": 50.0}
    assertions = [
        "body.refund.status == 'processed'",
        "body.refund.count == 1",  # fails here
        "body.refund.amount == args.amount",
    ]

    passed, failed_expr = evaluate_postcondition(assertions, body, args)
    assert passed is False
    assert failed_expr == "body.refund.count == 1"
