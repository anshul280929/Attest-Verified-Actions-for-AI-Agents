"""Verifier for independent state reading and postcondition assertion evaluation."""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from src.attest.contracts.evaluator import evaluate_postcondition
from src.attest.contracts.schema import ActionContract
from src.attest.contracts.template import parse_read_spec, substitute_path

logger = logging.getLogger(__name__)

VerificationVerdict = Literal["VERIFIED", "FAILED", "COMPENSATING", "UNKNOWN"]


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of an independent verification check."""

    verdict: VerificationVerdict
    failing_assertion: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _detect_partial_effect(body: dict[str, Any], contract_name: str) -> bool:
    """Heuristic check to determine if a violated postcondition has partial side effects."""
    if contract_name == "issue_refund":
        # Check if refund items were created or refunded_amount moved, but assertion still failed
        refund_summary = body.get("refund")
        if isinstance(refund_summary, dict) and refund_summary.get("count", 0) > 0:
            return True
        refunds_list = body.get("refunds")
        if isinstance(refunds_list, list) and len(refunds_list) > 0:
            return True
        if float(body.get("refunded_amount", 0.0)) > 0.0:
            return True

    if contract_name == "cancel_order" and body.get("status") == "CANCELLED":
        return False  # Already completely cancelled if reached here

    return False


async def verify_postcondition(
    contract: ActionContract,
    args: dict[str, Any],
    client: httpx.AsyncClient,
) -> VerificationResult:
    """Execute the contract's independent read and evaluate postcondition assertions.

    Fail-closed rules:
    - All assertions hold -> VERIFIED
    - Assertions fail + partial side effect detected -> COMPENSATING
    - Assertions fail + confirmed no effect -> FAILED
    - Read path unavailable / read error -> UNKNOWN (never assume verified)

    Args:
        contract: ActionContract declaring postcondition read path and assertions.
        args: Tool invocation arguments.
        client: Async HTTP client for read path (independent from write client).

    Returns:
        VerificationResult with verdict and diagnostic details.
    """
    method, path_template = parse_read_spec(contract.postcondition.read)
    try:
        path = substitute_path(path_template, args)
    except Exception as exc:
        logger.error(f"Failed to substitute read path template '{path_template}': {exc}")
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"error": f"Template substitution failed: {exc}"},
        )

    try:
        response = await client.request(method=method, url=path)
    except httpx.TimeoutException as exc:
        logger.warning(f"Verification read timed out for '{contract.name}': {exc}")
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"error": "Verification read timed out"},
        )
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        logger.warning(f"Verification read network error for '{contract.name}': {exc}")
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"error": f"Verification read network error: {exc}"},
        )
    except Exception as exc:
        logger.error(f"Unexpected error during verification read for '{contract.name}': {exc}")
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"error": f"Unexpected verification read exception: {exc}"},
        )

    # 404 on verification read means the entity does not exist -> no effect confirmed
    if response.status_code == 404:
        return VerificationResult(
            verdict="FAILED",
            detail={"status_code": 404, "error": "Target entity not found on read path"},
        )

    # Any other non-2xx status means read path is unavailable
    if not (200 <= response.status_code < 300):
        logger.warning(
            f"Verification read returned non-2xx status {response.status_code} for '{contract.name}'"
        )
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"status_code": response.status_code, "error": "Read path returned non-2xx"},
        )

    try:
        body = response.json()
        if not isinstance(body, dict):
            return VerificationResult(
                verdict="UNKNOWN",
                detail={"error": "Read response body is not a JSON object"},
            )
    except Exception as exc:
        return VerificationResult(
            verdict="UNKNOWN",
            detail={"error": f"Failed to parse read response JSON: {exc}"},
        )

    # Evaluate all assertions against the system state
    passed, failing_expr = evaluate_postcondition(
        contract.postcondition.assert_,
        body=body,
        args=args,
    )

    if passed:
        return VerificationResult(
            verdict="VERIFIED",
            detail={"body": body},
        )

    # Postcondition violated: determine if partial effect or complete failure
    is_partial = _detect_partial_effect(body, contract.name)
    verdict: VerificationVerdict = "COMPENSATING" if is_partial else "FAILED"

    logger.warning(
        f"Postcondition violated for '{contract.name}': assertion '{failing_expr}' failed. "
        f"Verdict: {verdict}"
    )

    return VerificationResult(
        verdict=verdict,
        failing_assertion=failing_expr,
        detail={"body": body, "failing_assertion": failing_expr},
    )
