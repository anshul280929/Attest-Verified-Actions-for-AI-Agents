"""URL template engine and read spec parser for action contracts."""

import re
from typing import Any


class TemplateSubstitutionError(Exception):
    """Raised when variable interpolation in a path template fails."""


_VAR_PATTERN = re.compile(r"\{([^{}]+)\}")


def substitute_path(
    path_template: str,
    args: dict[str, Any],
    downstream_ref: str | None = None,
    resource_key: str | None = None,
) -> str:
    """Substitute template variables into a URL path.

    Supports:
        - {args.foo} or {args.foo.bar}
        - {downstream_ref}
        - {resource_key}

    Args:
        path_template: Path string containing {variable} placeholders.
        args: Action input arguments dictionary.
        downstream_ref: Optional downstream transaction identifier.
        resource_key: Optional resource fencing identifier.

    Returns:
        Interpolated path string.

    Raises:
        TemplateSubstitutionError: If a referenced variable cannot be resolved.
    """

    def _replace(match: re.Match[str]) -> str:
        var_expr = match.group(1).strip()

        if var_expr == "downstream_ref":
            if downstream_ref is None:
                raise TemplateSubstitutionError("Variable 'downstream_ref' is None or not provided")
            return str(downstream_ref)

        if var_expr == "resource_key":
            if resource_key is None:
                raise TemplateSubstitutionError("Variable 'resource_key' is None or not provided")
            return str(resource_key)

        if var_expr.startswith("args."):
            key_path = var_expr[len("args.") :].split(".")
            val: Any = args
            for segment in key_path:
                if not isinstance(val, dict) or segment not in val:
                    raise TemplateSubstitutionError(
                        f"Variable '{var_expr}' not found in args: missing '{segment}'"
                    )
                val = val[segment]
            return str(val)

        # Direct arg name without 'args.' prefix
        if var_expr in args:
            return str(args[var_expr])

        raise TemplateSubstitutionError(f"Unknown template variable '{var_expr}'")

    return _VAR_PATTERN.sub(_replace, path_template)


def parse_read_spec(read_spec: str) -> tuple[str, str]:
    """Parse a contract postcondition read string into (method, path).

    Example:
        'GET /orders/{args.order_id}' -> ('GET', '/orders/{args.order_id}')
        '/orders/{args.order_id}' -> ('GET', '/orders/{args.order_id}')

    Args:
        read_spec: Read string from contract.

    Returns:
        tuple[str, str]: Uppercase HTTP method and path string.
    """
    cleaned = read_spec.strip()
    parts = cleaned.split(maxsplit=1)
    if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}:
        return parts[0].upper(), parts[1].strip()
    return "GET", cleaned
