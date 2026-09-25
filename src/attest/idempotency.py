"""Deterministic idempotency key derivation and canonical JSON serialization."""

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Serialize any JSON-compatible object into a deterministic canonical string.

    Rules:
    - Dict keys are sorted alphabetically at all levels.
    - No whitespace between tokens (separators=(',', ':')).
    - Floats and ints have consistent representation.
    - Unicode characters are preserved (ensure_ascii=False) or escaped consistently.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def derive_key(task_id: str, step: int, tool: str, args: dict[str, Any]) -> str:
    """Derive a deterministic SHA-256 idempotency key for an action.

    Formula: sha256("{task_id}|{step}|{tool}|{canonical_json(args)}")
    """
    raw_payload = f"{task_id}|{step}|{tool}|{canonical_json(args)}"
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
