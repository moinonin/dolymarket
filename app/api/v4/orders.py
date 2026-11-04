"""Private order management endpoints (submit, list, cancel, batch cancel)."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.engine.clob import MatchingEngine, OrderRejected
from app.models.domain import Market, Order, OutcomeToken, User
from app.services import collateral
from app.ws.broadcaster import broadcast_engine_events

router = APIRouter(prefix="/api/v4/prediction", tags=["orders"])


class CreateOrderRequest(BaseModel):
    market_id: str
    token_id: str
    side: str = Field(max_length=10)
    type: str = Field(default="LIMIT", max_length=10)
    price: float | None = None
    amount: float
    time_in_force: str = Field(default="GTC", max_length=10)
    post_only: bool = False

    @field_validator("side")
    @classmethod
    def _check_side(cls, v: str) -> str:
        v = v.upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        v = v.upper()
        if v not in ("LIMIT", "MARKET"):
            raise ValueError("type must be LIMIT or MARKET")
        return v

    @field_validator("time_in_force")
    @classmethod
    def _check_tif(cls, v: str) -> str:
        v = v.upper()
        if v not in ("GTC", "IOC", "FOK"):
            raise ValueError("time_in_force must be GTC, IOC or FOK")
        return v


def _order_payload(o: Order) -> dict:
    return {
        "id": o.id,
        "user_id": o.user_id,
        "market_id": o.market_id,
        "token_id": o.token_id,
        "side": o.side,
        "type": o.type,
        "price": float(o.price),
        "amount": float(o.amount),
        "filled_amount": float(o.filled_amount or 0),
        "status": o.status,
        "time_in_force": o.time_in_force,
        "post_only": bool(o.post_only),
        "created_at": str(o.created_at),
    }


@router.post("/orders", status_code=201)
async def submit_order(
    body: CreateOrderRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    token = (
        await session.execute(
            select(OutcomeToken).where(
                OutcomeToken.token_id == body.token_id,
                OutcomeToken.market_id == market.id,
            )
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found for this market")

    engine = MatchingEngine(broadcaster=broadcast_engine_events)
    try:
        order = await engine.submit_order(
            session,
            user.id,
            market,
            token,
            collateral,
            side=body.side,
            price=Decimal(str(body.price)) if body.price is not None else None,
            amount=Decimal(str(body.amount)),
            order_type=body.type,
            time_in_force=body.time_in_force,
            post_only=body.post_only,
        )
    except OrderRejected as exc:
        if exc.rejected:
            await session.commit()
            return {
                "order": {
                    "id": None,
                    "market_id": body.market_id,
                    "token_id": body.token_id,
                    "side": body.side,
                    "type": body.type,
                    "price": body.price,
                    "amount": body.amount,
                    "status": "REJECTED",
                    "reason": exc.detail,
                },
                "fills": [],
            }
        raise HTTPException(status_code=exc.http_status, detail=exc.detail)

    fills = (
        await session.execute(
            select(_fill_model()).where(_fill_model().taker_order_id == order.id)
        )
    ).scalars().all()

    payload = {
        "order": _order_payload(order),
        "fills": [
            {
                "id": f.id,
                "price": float(f.price),
                "shares": float(f.shares),
                "maker_fee": float(f.maker_fee or 0),
                "taker_fee": float(f.taker_fee or 0),
                "timestamp": str(f.timestamp),
            }
            for f in fills
        ],
    }
    return payload


def _fill_model():
    from app.models.domain import TradeFill

    return TradeFill


@router.get("/orders")
async def list_orders(
    market_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Returns only the authenticated user's orders."""
    stmt = select(Order).where(Order.user_id == user.id)
    if market_id:
        stmt = stmt.where(Order.market_id == market_id)
    if status:
        stmt = stmt.where(Order.status == status.upper())
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return {"orders": [_order_payload(o) for o in rows]}


@router.delete("/orders")
async def batch_cancel(
    market_id: str | None = None,
    condition_id: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Order).where(
        Order.user_id == user.id,
        Order.status.in_(("OPEN", "PARTIALLY_FILLED")),
    )
    if market_id:
        stmt = stmt.where(Order.market_id == market_id)
    if condition_id:
        stmt = stmt.join(Market, Order.market_id == Market.id).where(
            Market.condition_id == condition_id
        )
    if not market_id and not condition_id:
        raise HTTPException(
            status_code=422, detail="market_id or condition_id required"
        )
    engine = MatchingEngine()
    cancelled_ids = []
    for order in (await session.execute(stmt)).scalars().all():
        await engine.cancel_order(session, order, collateral)
        cancelled_ids.append(order.id)
    return {
        "cancelled_count": len(cancelled_ids),
        "cancelled_order_ids": cancelled_ids,
    }


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    order = (
        await session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")

    if order.status not in ("OPEN", "PARTIALLY_FILLED"):
        raise HTTPException(
            status_code=409,
            detail=f"Order is {order.status} and cannot be cancelled",
        )

    engine = MatchingEngine()
    result = await engine.cancel_order(session, order, collateral)
    status_changed = {"channel": "pred.orders", "user_id": user.id, **result}
    from app.ws.broadcaster import broadcast_engine_events as b

    await b([status_changed])
    return result
