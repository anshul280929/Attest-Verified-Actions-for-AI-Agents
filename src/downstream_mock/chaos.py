"""Chaos injection layer for downstream mock service."""

import logging
import random
from enum import StrEnum

from fastapi import Request

from src.downstream_mock.config import mock_settings

logger = logging.getLogger("downstream_mock.chaos")


class FaultProfile(StrEnum):
    NONE = "none"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"
    EMPTY_200 = "empty_200"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    PARTIAL_WRITE = "partial_write"


def resolve_fault_profile(request: Request) -> tuple[FaultProfile, random.Random]:
    """Resolve active fault profile and seeded PRNG from request headers or settings."""
    profile_hdr = request.headers.get("X-Fault-Profile")
    seed_hdr = request.headers.get("X-Fault-Seed")

    if seed_hdr is not None:
        try:
            seed = int(seed_hdr)
        except ValueError:
            seed = mock_settings.default_seed
    else:
        seed = mock_settings.default_seed

    rng = random.Random(seed)

    if profile_hdr:
        try:
            profile = FaultProfile(profile_hdr.lower())
        except ValueError:
            profile = FaultProfile.NONE
    else:
        try:
            profile = FaultProfile(mock_settings.default_fault_profile.lower())
        except ValueError:
            profile = FaultProfile.NONE

    return profile, rng
