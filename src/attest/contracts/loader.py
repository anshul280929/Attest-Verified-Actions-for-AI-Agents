"""Loader and registry for declarative action contracts."""

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from src.attest.contracts.schema import ActionContract

logger = logging.getLogger(__name__)


class ContractLoadError(Exception):
    """Raised when loading or validating a contract YAML fails."""


class ContractNotFoundError(Exception):
    """Raised when a requested contract name is not found in the registry."""


def load_contracts(directory: Path | str) -> dict[str, ActionContract]:
    """Load and validate all YAML contracts found in the given directory.

    Args:
        directory: Path to the directory containing *.yaml contracts.

    Returns:
        dict[str, ActionContract] mapping contract name to ActionContract instance.

    Raises:
        ContractLoadError: If directory does not exist, YAML is malformed,
            or schema validation fails.
    """
    contracts_path = Path(directory)
    if not contracts_path.exists():
        raise ContractLoadError(f"Contracts directory does not exist: {contracts_path}")
    if not contracts_path.is_dir():
        raise ContractLoadError(f"Contracts path is not a directory: {contracts_path}")

    loaded: dict[str, ActionContract] = {}
    yaml_files = sorted(list(contracts_path.glob("*.yaml")) + list(contracts_path.glob("*.yml")))

    for file_path in yaml_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
        except Exception as exc:
            raise ContractLoadError(
                f"Failed to parse YAML file '{file_path.name}': {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ContractLoadError(
                f"Contract file '{file_path.name}' must contain a YAML mapping/dictionary"
            )

        try:
            contract = ActionContract.model_validate(data)
        except ValidationError as exc:
            raise ContractLoadError(
                f"Schema validation failed for contract '{file_path.name}': {exc}"
            ) from exc

        if contract.name in loaded:
            raise ContractLoadError(
                f"Duplicate contract name '{contract.name}' found in '{file_path.name}'"
            )

        loaded[contract.name] = contract
        logger.info(f"Loaded contract '{contract.name}' from {file_path.name}")

    return loaded
