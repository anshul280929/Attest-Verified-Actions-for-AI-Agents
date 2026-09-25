"""In-memory state store for downstream orders and refunds."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Order:
    order_id: str
    customer_id: str
    total_amount: float
    status: str  # PAID, CANCELLED, REFUNDED, PARTIALLY_REFUNDED
    refunded_amount: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Refund:
    refund_id: str
    order_id: str
    amount: float
    reason: str
    idempotency_key: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DownstreamStore:
    """Thread-safe in-memory store for mock orders, refunds, and deduplication keys."""

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.refunds: dict[str, Refund] = {}
        self.processed_idempotency_keys: dict[str, Any] = {}
        self.seed_defaults()

    def seed_defaults(self) -> None:
        """Seed default mock data for benchmark and integration scenarios."""
        self.orders["order-12345"] = Order(
            order_id="order-12345",
            customer_id="cust-101",
            total_amount=100.0,
            status="PAID",
            refunded_amount=0.0,
            items=[{"sku": "ITEM-A", "qty": 1, "price": 100.0}],
        )
        self.orders["order-67890"] = Order(
            order_id="order-67890",
            customer_id="cust-102",
            total_amount=250.0,
            status="PAID",
            refunded_amount=0.0,
            items=[{"sku": "ITEM-B", "qty": 2, "price": 125.0}],
        )

    def reset(self) -> None:
        """Clear all dynamic state and re-seed defaults."""
        self.orders.clear()
        self.refunds.clear()
        self.processed_idempotency_keys.clear()
        self.seed_defaults()


store = DownstreamStore()
