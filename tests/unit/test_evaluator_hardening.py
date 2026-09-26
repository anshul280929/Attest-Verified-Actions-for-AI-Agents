"""Property-based and adversarial hardening tests for sandboxed AST evaluator.

Enforces CONT-03:
- Absolute rejection of code execution, builtins, dunders, and escapes
- Fuzzing with Hypothesis to verify safe failure modes
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from src.attest.contracts.evaluator import (
    EvaluationError,
    UnsafeExpressionError,
    evaluate,
)
from src.attest.contracts.schema import ActionContract

ATTACK_VECTORS = [
    "__import__('os').system('echo pwned')",
    "__import__('sys').exit(1)",
    "exec('import os')",
    "eval('2 + 2')",
    "().__class__.__bases__[0].__subclasses__()",
    "''.__class__.__mro__[1].__subclasses__()",
    "globals()",
    "locals()",
    "vars()",
    "dir()",
    "getattr(object, '__class__')",
    "setattr(object, 'attr', 1)",
    "delattr(object, 'attr')",
    "breakpoint()",
    "exit()",
    "quit()",
    "help()",
    "open('/etc/passwd')",
    "lambda x: x + 1",
    "[x for x in [1, 2, 3]]",
    "{x: x for x in [1, 2, 3]}",
    "{x for x in [1, 2, 3]}",
    "(x for x in [1, 2, 3])",
    "f'injection {1 + 1}'",
    "yield 42",
    "await something()",
    "__builtins__['eval']('1+1')",
    "body.__class__",
    "args.__dict__",
    "body.__subclasses__()",
]


@pytest.mark.parametrize("attack_string", ATTACK_VECTORS)
def test_evaluator_rejects_adversarial_patterns(attack_string: str) -> None:
    """Verify that every known sandbox escape pattern is blocked at AST validation."""
    with pytest.raises(UnsafeExpressionError):
        evaluate(attack_string, {"body": {}, "args": {}})


def test_evaluator_ast_depth_limit() -> None:
    """Verify that excessive AST nesting is rejected to prevent stack exhaustion."""
    # Nesting 22 binary ops exceeds MAX_AST_DEPTH (20)
    deep_expr = "1"
    for _ in range(22):
        deep_expr = f"({deep_expr} + 1)"

    with pytest.raises(UnsafeExpressionError) as exc_info:
        evaluate(deep_expr, {})
    assert "exceeds maximum AST depth" in str(exc_info.value)


@given(st.text(min_size=1, max_size=100))
@settings(max_examples=200, deadline=None)
def test_evaluator_fuzz_random_strings(random_str: str) -> None:
    """Fuzz evaluator with arbitrary text; must only produce controlled errors or booleans/scalars."""
    try:
        res = evaluate(random_str, {"body": {"status": "PAID"}, "args": {"id": 1}})
        # If it returned without exception, the result must be a standard python type
        assert isinstance(res, (bool, int, float, str, list, tuple, dict, type(None)))
    except (UnsafeExpressionError, EvaluationError):
        pass


@given(
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
)
def test_evaluator_fuzz_arithmetic(a: int, b: int) -> None:
    """Fuzz safe arithmetic and comparisons to verify correctness."""
    context = {"x": a, "y": b}
    assert evaluate("x + y == y + x", context) is True
    assert evaluate("x - y == -(y - x)", context) is True
    assert evaluate("x == x", context) is True
    assert evaluate("x != x + 1", context) is True


def test_schema_validation_rejections() -> None:
    """Test schema validation rejects invalid configs according to CONT-01."""
    # Negative timeout
    with pytest.raises(ValidationError):
        ActionContract.model_validate(
            {
                "name": "invalid_timeout",
                "resource_key": "res",
                "downstream": {
                    "method": "POST",
                    "path": "/api",
                    "timeout_ms": -50,
                },
                "postcondition": {
                    "read": "GET /api",
                    "assert": ["body.ok == True"],
                },
            }
        )

    # Zero timeout
    with pytest.raises(ValidationError):
        ActionContract.model_validate(
            {
                "name": "zero_timeout",
                "resource_key": "res",
                "downstream": {
                    "method": "POST",
                    "path": "/api",
                    "timeout_ms": 0,
                },
                "postcondition": {
                    "read": "GET /api",
                    "assert": ["body.ok == True"],
                },
            }
        )

    # Empty assert list
    with pytest.raises(ValidationError):
        ActionContract.model_validate(
            {
                "name": "empty_assert",
                "resource_key": "res",
                "downstream": {
                    "method": "POST",
                    "path": "/api",
                },
                "postcondition": {
                    "read": "GET /api",
                    "assert": [],
                },
            }
        )
