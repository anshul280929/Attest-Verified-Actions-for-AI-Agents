import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from src.attest.contracts.schema import ActionContract
from src.attest.contracts.template import substitute_path

logger = logging.getLogger(__name__)

ExecutionClassification = Literal["definite_success", "definite_failure", "ambiguous"]


@dataclass(frozen=True)
class ExecutionResult:
    """Classified result of a downstream mutation attempt."""

    classification: ExecutionClassification
    status_code: int | None = None
    body: dict[str, Any] | None = None
    raw_text: str | None = None
    downstream_ref: str | None = None
    error_detail: str | None = None


async def execute_contract(
    contract: ActionContract,
    args: dict[str, Any],
    idempotency_key: str,
    client: httpx.AsyncClient,
    extra_headers: dict[str, str] | None = None,
) -> ExecutionResult:
    """Execute a downstream mutation based on an ActionContract and classify the result.

    Rules (fail closed):
    - 2xx with non-empty JSON body -> definite_success
    - Status in contract.downstream.definite_failure_statuses -> definite_failure
    - 2xx with empty body -> ambiguous (silent no-op or unconfirmed commit)
    - 5xx, timeouts, connection resets -> ambiguous
    - Any unexpected status not in definite_failure_statuses -> ambiguous

    Args:
        contract: ActionContract defining downstream endpoint and rules.
        args: Input arguments for the tool call.
        idempotency_key: Deterministic idempotency key to forward.
        client: Async HTTP client for downstream communication.
        extra_headers: Optional extra headers (e.g. chaos injection headers) to forward.

    Returns:
        ExecutionResult containing classification, status code, body, and refs.
    """
    path = substitute_path(contract.downstream.path, args)
    method = contract.downstream.method.upper()
    headers = {contract.downstream.idempotency_header: idempotency_key}
    if extra_headers:
        headers.update(extra_headers)
    timeout_sec = contract.downstream.timeout_ms / 1000.0

    try:
        req_coro = (
            client.request(
                method=method,
                url=path,
                json=args,
                headers=headers,
                timeout=timeout_sec,
            )
            if method in {"POST", "PUT", "PATCH"}
            else client.request(
                method=method,
                url=path,
                headers=headers,
                timeout=timeout_sec,
            )
        )
        response = await asyncio.wait_for(req_coro, timeout=timeout_sec)
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning(f"Downstream call timed out for contract '{contract.name}': {exc}")
        return ExecutionResult(
            classification="ambiguous",
            error_detail=f"Downstream timeout after {contract.downstream.timeout_ms}ms",
        )
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        logger.warning(f"Downstream connection error for contract '{contract.name}': {exc}")
        return ExecutionResult(
            classification="ambiguous",
            error_detail=f"Downstream connection error: {exc}",
        )
    except Exception as exc:
        logger.error(f"Unexpected downstream client error for contract '{contract.name}': {exc}")
        return ExecutionResult(
            classification="ambiguous",
            error_detail=f"Downstream client exception: {exc}",
        )

    # Inspect response status and body
    status_code = response.status_code
    raw_text = response.text

    # Check for empty body (e.g. empty_200 fault profile)
    if not response.content or not raw_text.strip():
        logger.warning(
            f"Downstream returned empty body with status {status_code} for contract '{contract.name}'"
        )
        return ExecutionResult(
            classification="ambiguous",
            status_code=status_code,
            raw_text="",
            error_detail="Downstream returned empty body",
        )

    # Attempt to parse body as JSON
    parsed_json: dict[str, Any] | None = None
    try:
        json_data = response.json()
        if isinstance(json_data, dict):
            parsed_json = json_data
    except Exception:
        parsed_json = None

    # Classify response:
    # 1. 2xx Success with content
    if 200 <= status_code < 300:
        downstream_ref: str | None = None
        if parsed_json:
            downstream_ref = (
                parsed_json.get("refund_id")
                or parsed_json.get("order_id")
                or parsed_json.get("id")
            )
        return ExecutionResult(
            classification="definite_success",
            status_code=status_code,
            body=parsed_json,
            raw_text=raw_text,
            downstream_ref=str(downstream_ref) if downstream_ref else None,
        )

    # 2. Definite failure (configured known-no-commit statuses, e.g. 400, 404)
    if status_code in contract.downstream.definite_failure_statuses:
        return ExecutionResult(
            classification="definite_failure",
            status_code=status_code,
            body=parsed_json,
            raw_text=raw_text,
            error_detail=f"Definite failure status {status_code}: {raw_text}",
        )

    # 3. Everything else (5xx, unlisted 4xx, etc.) is ambiguous
    logger.warning(
        f"Downstream returned ambiguous status {status_code} for contract '{contract.name}'"
    )
    return ExecutionResult(
        classification="ambiguous",
        status_code=status_code,
        body=parsed_json,
        raw_text=raw_text,
        error_detail=f"Ambiguous downstream status {status_code}",
    )
