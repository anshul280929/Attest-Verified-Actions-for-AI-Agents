"""Sandboxed AST expression evaluator for contract assertions.

Evaluates postcondition assert expressions against system state.
Guaranteed safe:
- Pure AST walk allowlist
- No calls (ast.Call forbidden)
- No imports (ast.Import, ast.ImportFrom forbidden)
- No dunder access (__class__, __subclasses__, etc. forbidden)
- Max tree depth limit (default 20)
- Context-only name resolution (no globals, no builtins)
"""

import ast
from typing import Any


class UnsafeExpressionError(Exception):
    """Raised when an expression contains disallowed AST nodes or dunder patterns."""


class EvaluationError(Exception):
    """Raised when expression evaluation fails due to missing keys, type errors, etc."""


MAX_AST_DEPTH = 20


def _check_ast_safety(node: ast.AST, depth: int = 0) -> None:
    """Recursively inspect AST nodes against allowlist and depth limits."""
    if depth > MAX_AST_DEPTH:
        raise UnsafeExpressionError(f"Expression exceeds maximum AST depth of {MAX_AST_DEPTH}")

    match node:
        case ast.Expression():
            _check_ast_safety(node.body, depth + 1)

        case ast.Compare():
            _check_ast_safety(node.left, depth + 1)
            for comp in node.comparators:
                _check_ast_safety(comp, depth + 1)

        case ast.BoolOp():
            for val in node.values:
                _check_ast_safety(val, depth + 1)

        case ast.UnaryOp():
            _check_ast_safety(node.operand, depth + 1)

        case ast.BinOp():
            _check_ast_safety(node.left, depth + 1)
            _check_ast_safety(node.right, depth + 1)

        case ast.Attribute():
            if node.attr.startswith("__"):
                raise UnsafeExpressionError(f"Dunder attribute access forbidden: {node.attr}")
            _check_ast_safety(node.value, depth + 1)

        case ast.Subscript():
            _check_ast_safety(node.value, depth + 1)
            _check_ast_safety(node.slice, depth + 1)

        case ast.Name():
            if node.id.startswith("__"):
                raise UnsafeExpressionError(f"Dunder name access forbidden: {node.id}")

        case ast.Constant():
            pass

        case ast.List() | ast.Tuple():
            for elt in node.elts:
                _check_ast_safety(elt, depth + 1)

        case ast.Dict():
            for k in node.keys:
                if k is not None:
                    _check_ast_safety(k, depth + 1)
            for v in node.values:
                _check_ast_safety(v, depth + 1)

        case (
            ast.Eq()
            | ast.NotEq()
            | ast.Lt()
            | ast.LtE()
            | ast.Gt()
            | ast.GtE()
            | ast.In()
            | ast.NotIn()
            | ast.Is()
            | ast.IsNot()
            | ast.And()
            | ast.Or()
            | ast.Not()
            | ast.Add()
            | ast.Sub()
            | ast.Mult()
            | ast.Div()
            | ast.FloorDiv()
            | ast.Mod()
            | ast.USub()
            | ast.UAdd()
            | ast.Load()
        ):
            pass

        case _:
            raise UnsafeExpressionError(
                f"Disallowed AST node type '{type(node).__name__}' in expression"
            )


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    """Evaluate an AST node within the provided dictionary context."""
    match node:
        case ast.Constant():
            return node.value

        case ast.Name():
            if node.id in context:
                return context[node.id]
            # Recognize None, True, False if parsed as Name
            if node.id == "None":
                return None
            if node.id == "True":
                return True
            if node.id == "False":
                return False
            raise EvaluationError(f"Variable '{node.id}' not found in context")

        case ast.Attribute():
            target = _eval_node(node.value, context)
            if target is None:
                raise EvaluationError(f"Cannot access attribute '{node.attr}' on None")
            if isinstance(target, dict):
                if node.attr in target:
                    return target[node.attr]
                raise EvaluationError(f"Key '{node.attr}' not found in dict")
            if hasattr(target, node.attr):
                return getattr(target, node.attr)
            raise EvaluationError(f"Attribute '{node.attr}' not found on {type(target).__name__}")

        case ast.Subscript():
            target = _eval_node(node.value, context)
            key = _eval_node(node.slice, context)
            try:
                return target[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise EvaluationError(f"Subscript lookup failed: {exc}") from exc

        case ast.Compare():
            left_val = _eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right_val = _eval_node(comparator, context)
                passed = _eval_compare_op(op, left_val, right_val)
                if not passed:
                    return False
                left_val = right_val
            return True

        case ast.BoolOp():
            if isinstance(node.op, ast.And):
                return all(bool(_eval_node(val, context)) for val in node.values)
            if isinstance(node.op, ast.Or):
                return any(bool(_eval_node(val, context)) for val in node.values)
            raise EvaluationError(f"Unsupported BoolOp {type(node.op).__name__}")

        case ast.UnaryOp():
            operand = _eval_node(node.operand, context)
            match node.op:
                case ast.Not():
                    return not bool(operand)
                case ast.USub():
                    return -operand
                case ast.UAdd():
                    return +operand
                case _:
                    raise EvaluationError(f"Unsupported UnaryOp {type(node.op).__name__}")

        case ast.BinOp():
            left = _eval_node(node.left, context)
            right = _eval_node(node.right, context)
            match node.op:
                case ast.Add():
                    return left + right
                case ast.Sub():
                    return left - right
                case ast.Mult():
                    return left * right
                case ast.Div():
                    return left / right
                case ast.FloorDiv():
                    return left // right
                case ast.Mod():
                    return left % right
                case _:
                    raise EvaluationError(f"Unsupported BinOp {type(node.op).__name__}")

        case ast.List():
            return [_eval_node(elt, context) for elt in node.elts]

        case ast.Tuple():
            return tuple(_eval_node(elt, context) for elt in node.elts)

        case ast.Dict():
            keys = [_eval_node(k, context) if k is not None else None for k in node.keys]
            values = [_eval_node(v, context) for v in node.values]
            return dict(zip(keys, values, strict=True))

        case _:
            raise UnsafeExpressionError(f"Unsupported AST node during evaluation: {type(node).__name__}")


def _eval_compare_op(op: ast.cmpop, left: Any, right: Any) -> bool:
    """Evaluate a single binary comparison operation."""
    match op:
        case ast.Eq():
            return bool(left == right)
        case ast.NotEq():
            return bool(left != right)
        case ast.Lt():
            return bool(left < right)
        case ast.LtE():
            return bool(left <= right)
        case ast.Gt():
            return bool(left > right)
        case ast.GtE():
            return bool(left >= right)
        case ast.In():
            return bool(left in right)
        case ast.NotIn():
            return bool(left not in right)
        case ast.Is():
            return bool(left is right)
        case ast.IsNot():
            return bool(left is not right)
        case _:
            raise EvaluationError(f"Unsupported comparison operator: {type(op).__name__}")


def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """Parse, inspect for safety, and evaluate an expression against context.

    Args:
        expression: Python-like expression string.
        context: Variables dictionary accessible in the expression.

    Returns:
        Result of expression evaluation.

    Raises:
        UnsafeExpressionError: If the expression fails the safety allowlist.
        EvaluationError: If runtime evaluation encounters a missing key or type error.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"Syntax error in expression '{expression}': {exc}") from exc

    _check_ast_safety(tree)
    return _eval_node(tree.body, context)


def evaluate_postcondition(
    expressions: list[str],
    body: dict[str, Any],
    args: dict[str, Any],
) -> tuple[bool, str | None]:
    """Evaluate a list of contract assertions against read response body and call args.

    Args:
        expressions: List of boolean assert expression strings.
        body: Deserialized JSON body from the read path.
        args: Original arguments passed to the action tool.

    Returns:
        tuple[bool, str | None]: (all_passed, first_failing_expression)
    """
    context: dict[str, Any] = {
        "body": body,
        "args": args,
    }

    for expr in expressions:
        try:
            res = evaluate(expr, context)
            if not bool(res):
                return False, expr
        except (EvaluationError, UnsafeExpressionError):
            return False, expr

    return True, None
