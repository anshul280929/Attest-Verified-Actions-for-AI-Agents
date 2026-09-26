"""Downstream mock router for order inspection and cancellation."""

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from src.downstream_mock.chaos import FaultProfile, resolve_fault_profile
from src.downstream_mock.config import mock_settings
from src.downstream_mock.store import store

router = APIRouter(prefix="/orders", tags=["orders"])


class CancelResponse(BaseModel):
    order_id: str
    status: str
    cancelled: bool = True


@router.get("/{order_id}")
async def get_order(order_id: str) -> dict[str, Any]:
    """Verification read path for order status."""
    order = store.orders.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )
    order_refunds = [r for r in store.refunds.values() if r.order_id == order_id]
    refund_summary = {
        "status": "processed" if order.refunded_amount > 0 else "none",
        "amount": order.refunded_amount,
        "count": len(order_refunds),
    }
    return {
        "order_id": order.order_id,
        "customer_id": order.customer_id,
        "total_amount": order.total_amount,
        "status": order.status,
        "refunded_amount": order.refunded_amount,
        "items": order.items,
        "created_at": order.created_at,
        "refund": refund_summary,
        "refunds": [
            {
                "refund_id": r.refund_id,
                "amount": r.amount,
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in order_refunds
        ],
    }


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Response:
    """Cancel an order with chaos fault injection support."""
    order = store.orders.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )

    profile, rng = resolve_fault_profile(request)

    if profile == FaultProfile.EMPTY_200:
        if rng.random() < 0.5:
            order.status = "CANCELLED"
        return Response(status_code=200, content="", media_type="text/plain")

    if profile == FaultProfile.TIMEOUT_AFTER_COMMIT:
        order.status = "CANCELLED"
        await asyncio.sleep(mock_settings.timeout_delay_seconds)
        return Response(
            content=CancelResponse(order_id=order_id, status=order.status).model_dump_json(),
            media_type="application/json",
        )

    if profile == FaultProfile.PARTIAL_WRITE:
        # Commit note but don't update status
        return Response(
            content=CancelResponse(
                order_id=order_id, status=order.status, cancelled=False
            ).model_dump_json(),
            media_type="application/json",
        )

    # NONE or normal execution
    order.status = "CANCELLED"
    return Response(
        content=CancelResponse(order_id=order_id, status=order.status).model_dump_json(),
        media_type="application/json",
    )
