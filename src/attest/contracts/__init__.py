"""Contracts package providing registry, loader, schemas, and evaluator."""

from src.attest.contracts.loader import (
    ContractLoadError,
    ContractNotFoundError,
    load_contracts,
)
from src.attest.contracts.schema import ActionContract


class ContractRegistry:
    """Thread-safe registry for validated action contracts."""

    def __init__(self, contracts: dict[str, ActionContract] | None = None) -> None:
        self._contracts: dict[str, ActionContract] = dict(contracts or {})

    def get(self, name: str) -> ActionContract | None:
        """Lookup contract by tool name, or return None if not found."""
        return self._contracts.get(name)

    def require(self, name: str) -> ActionContract:
        """Lookup contract by tool name or raise ContractNotFoundError."""
        if name not in self._contracts:
            known = sorted(list(self._contracts.keys()))
            raise ContractNotFoundError(
                f"No contract registered for tool '{name}'. Known tools: {known}"
            )
        return self._contracts[name]

    def register(self, contract: ActionContract) -> None:
        """Register a single contract."""
        self._contracts[contract.name] = contract

    @property
    def contracts(self) -> dict[str, ActionContract]:
        """Return a copy of the registered contracts dictionary."""
        return dict(self._contracts)


__all__ = [
    "ActionContract",
    "ContractLoadError",
    "ContractNotFoundError",
    "ContractRegistry",
    "load_contracts",
]
