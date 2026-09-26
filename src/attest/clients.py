"""HTTP client factories for downstream executor (write) and verifier (read).

Separate client instances enforce independence between write and read paths,
preventing cross-contamination of connection pools or headers.
"""

import httpx

from src.attest.config import settings


def create_downstream_client(base_url: str | None = None) -> httpx.AsyncClient:
    """Create an HTTP client configured for downstream write mutations."""
    return httpx.AsyncClient(
        base_url=base_url or settings.downstream_base_url,
        timeout=settings.default_timeout_seconds,
    )


def create_verifier_client(base_url: str | None = None) -> httpx.AsyncClient:
    """Create an independent HTTP client configured for state verification reads."""
    return httpx.AsyncClient(
        base_url=base_url or settings.downstream_base_url,
        timeout=settings.default_timeout_seconds,
    )
