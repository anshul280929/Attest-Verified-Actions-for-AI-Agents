"""Downstream mock router for refund issuance and inspection."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from src.downstream_mock.chaos import FaultProfile, resolve_fault_profile
from src.downstream_mock.config import mock_settings
from src.downstream_mock.store import Refund, store

router = APIRouter(prefix="/refunds", tags=["refunds"])


class RefundRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    reason: str = Field(default="customer_request")


class RefundResponse(BaseModel):
    refund_id: str
    order_id: str
    amount: float
    status: str = "COMPLETED"


@router.post("")
async def create_refund(
    payload: RefundRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Response:
    """Create a refund against an order with fault injection profiles."""
    order = store.orders.get(payload.order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {payload.order_id} not found",
        )

    # Idempotency check: if key already processed under normal circumstances, return previous result
    if idempotency_key and idempotency_key in store.processed_idempotency_keys:
        cached = store.processed_idempotency_keys[idempotency_key]
        return Response(
            content=cached.model_dump_json(),
            media_type="application/json",
        )

    profile, rng = resolve_fault_profile(request)

    if profile == FaultProfile.EMPTY_200:
        # Commit in ~50% of cases based on deterministic seed
        if rng.random() < 0.5:
            refund_id = f"ref-{uuid.uuid4().hex[:8]}"
            new_refund = Refund(
                refund_id=refund_id,
                order_id=payload.order_id,
                amount=payload.amount,
                reason=payload.reason,
                idempotency_key=idempotency_key,
            )
            store.refunds[refund_id] = new_refund
            order.refunded_amount += payload.amount
            if order.refunded_amount >= order.total_amount:
                order.status = "REFUNDED"
            else:
                order.status = "PARTIALLY_REFUNDED"
        return Response(status_code=200, content="", media_type="text/plain")

    if profile == FaultProfile.TIMEOUT_AFTER_COMMIT:
        # Write committed, but server hangs past client timeout budget
        refund_id = f"ref-{uuid.uuid4().hex[:8]}"
        new_refund = Refund(
            refund_id=refund_id,
            order_id=payload.order_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
        store.refunds[refund_id] = new_refund
        order.refunded_amount += payload.amount
        order.status = (
            "REFUNDED" if order.refunded_amount >= order.total_amount else "PARTIALLY_REFUNDED"
        )
        resp = RefundResponse(refund_id=refund_id, order_id=payload.order_id, amount=payload.amount)
        if idempotency_key:
            store.processed_idempotency_keys[idempotency_key] = resp

        await asyncio.sleep(mock_settings.timeout_delay_seconds)
        return Response(content=resp.model_dump_json(), media_type="application/json")

    if profile == FaultProfile.DUPLICATE_DELIVERY:
        # Handler executes twice: two refunds created, double deducted
        refund_id_1 = f"ref-{uuid.uuid4().hex[:8]}"
        refund_id_2 = f"ref-{uuid.uuid4().hex[:8]}"
        store.refunds[refund_id_1] = Refund(
            refund_id=refund_id_1,
            order_id=payload.order_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
        store.refunds[refund_id_2] = Refund(
            refund_id=refund_id_2,
            order_id=payload.order_id,
            amount=payload.amount,
            reason=f"{payload.reason}_duplicate",
            idempotency_key=idempotency_key,
        )
        order.refunded_amount += payload.amount * 2
        order.status = (
            "REFUNDED" if order.refunded_amount >= order.total_amount else "PARTIALLY_REFUNDED"
        )
        resp = RefundResponse(
            refund_id=refund_id_2, order_id=payload.order_id, amount=payload.amount
        )
        return Response(content=resp.model_dump_json(), media_type="application/json")

    if profile == FaultProfile.PARTIAL_WRITE:
        # Creates refund record but fails to update order refunded_amount or status
        refund_id = f"ref-{uuid.uuid4().hex[:8]}"
        store.refunds[refund_id] = Refund(
            refund_id=refund_id,
            order_id=payload.order_id,
            amount=payload.amount,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
        # Note: order.refunded_amount and order.status NOT updated!
        resp = RefundResponse(refund_id=refund_id, order_id=payload.order_id, amount=payload.amount)
        return Response(content=resp.model_dump_json(), media_type="application/json")

    # NONE profile (normal clean execution)
    refund_id = f"ref-{uuid.uuid4().hex[:8]}"
    new_refund = Refund(
        refund_id=refund_id,
        order_id=payload.order_id,
        amount=payload.amount,
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    store.refunds[refund_id] = new_refund
    order.refunded_amount += payload.amount
    order.status = (
        "REFUNDED" if order.refunded_amount >= order.total_amount else "PARTIALLY_REFUNDED"
    )
    resp = RefundResponse(refund_id=refund_id, order_id=payload.order_id, amount=payload.amount)

    if idempotency_key:
        store.processed_idempotency_keys[idempotency_key] = resp

    return Response(content=resp.model_dump_json(), media_type="application/json")


@router.get("/{refund_id}")
async def get_refund(refund_id: str) -> dict[str, Any]:
    """Retrieve refund details by refund ID."""
    refund = store.refunds.get(refund_id)
    if refund is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Refund {refund_id} not found",
        )
    return {
        "refund_id": refund.refund_id,
        "order_id": refund.order_id,
        "amount": refund.amount,
        "reason": refund.reason,
        "idempotency_key": refund.idempotency_key,
        "created_at": refund.created_at,
    }
