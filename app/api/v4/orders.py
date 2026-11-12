"""Private order management endpoints (submit, list, cancel, batch cancel)."""
import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.engine.clob import MatchingEngine, OrderRejected, OrderBook
from app.models.domain import (
    Desk,
    DeskPosition,
    IdempotencyRecord,
    Market,
    Order,
    OutcomeToken,
    TradeFill,
    User,
)
from app.services import collateral, copy_engine, desk_track_record
from app.ws.broadcaster import broadcast_engine_events

logger = logging.getLogger("app.orders")

router = APIRouter(prefix="/api/v4/prediction", tags=["orders"])


class CreateOrderRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    token_id: str = Field(min_length=1, max_length=100)
    side: str = Field(max_length=10)
    type: str = Field(default="LIMIT", max_length=10)
    # Decimal (not float) so NaN/Infinity can never reach Decimal arithmetic
    # and binary rounding never touches money columns. Bounds mirror the
    # engine's MIN_PRICE/MAX_PRICE; tick alignment stays engine-side.
    # Loose schema bounds (0..1) so the engine's own MIN_PRICE/MAX_PRICE
    # rejection (400 with a precise message) is what surfaces, while NaN/Inf
    # and binary float rounding are still blocked by the validators below.
    price: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("1")
    )
    amount: Decimal = Field(gt=0, le=Decimal("1000000"))
    time_in_force: str = Field(default="GTC", max_length=10)
    post_only: bool = False
    desk_id: str | None = Field(default=None, max_length=64)

    @field_validator("side", "price", "amount")
    @classmethod
    def _check_fields(cls, v, info):
        field = info.field_name
        if field == "side":
            v = v.upper()
            if v not in ("BUY", "SELL"):
                raise ValueError("side must be BUY or SELL")
            return v
        if v is not None and not v.is_finite():
            raise ValueError("must be a finite number")
        return v

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


def _request_hash(body: CreateOrderRequest) -> str:
    # Decimal fields are not JSON-serializable by default; str() keeps the
    # canonical form stable for hashing purposes.
    canonical = json.dumps(
        body.model_dump(), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _replay_idempotent(
    session: AsyncSession,
    user_id: str,
    key: str | None,
    request_hash: str,
) -> JSONResponse | None:
    if not key:
        return None
    row = (
        await session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="X-Idempotency-Key reused with a different order payload",
        )
    return JSONResponse(
        status_code=row.status_code,
        content=json.loads(row.response_json),
        headers={"Idempotent-Replay": "true"},
    )


def _store_idempotent(
    session: AsyncSession,
    user_id: str,
    key: str | None,
    request_hash: str,
    payload: dict,
    status_code: int = 201,
) -> None:
    if not key:
        return
    session.add(
        IdempotencyRecord(
            user_id=user_id,
            key=key,
            request_hash=request_hash,
            status_code=status_code,
            response_json=json.dumps(payload, default=str),
        )
    )


@router.post("/orders", status_code=201)
async def submit_order(
    body: CreateOrderRequest,
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 255:
            raise HTTPException(
                status_code=422,
                detail="X-Idempotency-Key must be 1-255 characters",
            )

    req_hash = _request_hash(body)
    replay = await _replay_idempotent(
        session, user.id, idempotency_key, req_hash
    )
    if replay is not None:
        return replay

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

    # Pro Desks: optional desk tagging and conflict guards.
    desk = None
    if body.desk_id is not None:
        desk = (await session.execute(select(Desk).where(Desk.id == body.desk_id))).scalar_one_or_none()
        if desk is None:
            raise HTTPException(status_code=404, detail="Desk not found")
        if desk.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="DESK_ORDER_FORBIDDEN")
        if desk.status != "ACTIVE":
            raise HTTPException(status_code=409, detail="DESK_NOT_ACTIVE")
    else:
        # Untagged personal order: reject if the caller's ACTIVE desk holds a
        # non-zero position in this market (anti front-running).
        caller_desk = (
            await session.execute(
                select(Desk).where(
                    Desk.owner_user_id == user.id, Desk.status == "ACTIVE"
                )
            )
        ).scalar_one_or_none()
        if caller_desk is not None:
            pos = (
                await session.execute(
                    select(DeskPosition).where(
                        DeskPosition.desk_id == caller_desk.id,
                        DeskPosition.market_id == market.id,
                    )
                )
            ).scalar_one_or_none()
            if pos is not None and Decimal(str(pos.shares)) != 0:
                raise HTTPException(status_code=409, detail="DESK_MARKET_CONFLICT")

    engine = MatchingEngine(broadcaster=broadcast_engine_events)
    try:
        order = await engine.submit_order(
            session,
            user.id,
            market,
            token,
            collateral,
            side=body.side,
            price=body.price,
            amount=body.amount,
            order_type=body.type,
            time_in_force=body.time_in_force,
            post_only=body.post_only,
            desk_id=desk.id if desk is not None else None,
        )
    except OrderRejected as exc:
        # Rejections are errors, not creations: the route's declared 201 must
        # only ever mean "order created". No idempotent result is stored for a
        # rejected submission so a retry is a genuine retry.
        raise HTTPException(status_code=exc.http_status, detail=exc.detail)
    except HTTPException as exc:
        if desk is not None and exc.status_code == 400 and "insufficient" in (exc.detail or "").lower():
            desk.status = "SUSPENDED"
            desk.review_note = "INSUFFICIENT_OPERATOR_FUNDS"
            desk.suspended_at = datetime.now(UTC)
            await session.commit()
        raise

    if order.status == "REJECTED":
        # Self-trade prevention returns a REJECTED order instead of raising;
        # surface it as the rejection it is.
        raise HTTPException(status_code=409, detail="SELF_TRADE_PREVENTED")

    fills = (
        await session.execute(
            select(TradeFill).where(TradeFill.taker_order_id == order.id)
        )
    ).scalars().all()

    # Pro Desks: update the desk position and mirror each fill to followers.
    # Runs inside a SAVEPOINT so a mirroring failure rolls back only the
    # mirroring writes — the desk's own fill and order stay committed.
    if desk is not None:
        try:
            async with session.begin_nested():
                await desk_track_record.maybe_apply_breakers(session, desk)
                for f in fills:
                    await copy_engine._update_desk_position(
                        session,
                        desk,
                        market,
                        token,
                        Decimal(str(f.shares)),
                        Decimal(str(f.price)),
                        body.side,
                    )
                if desk.status == "ACTIVE":
                    for f in fills:
                        await copy_engine.mirror_source_fill(
                            session, desk, f, market, token, broadcast_engine_events
                        )
        except Exception:
            logger.exception(
                "copy mirroring failed for desk %s (order %s)", desk.id, order.id
            )

    payload = {
        "order": _order_payload(order),
        "fills": [
            {
                "id": f.id,
                "price": float(f.price),
                "shares": float(f.shares),
                "maker_fee": float(f.maker_fee or 0),
                "taker_fee": float(f.taker_fee or 0),
                "sequence_id": f.sequence_id,
                "timestamp": str(f.timestamp),
            }
            for f in fills
        ],
    }
    _store_idempotent(session, user.id, idempotency_key, req_hash, payload)
    return payload


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
    depth_events: list[dict] = []
    seen_tokens: set[str] = set()
    for order in (await session.execute(stmt)).scalars().all():
        await engine.cancel_order(session, order, collateral)
        cancelled_ids.append(order.id)
        if order.token_id not in seen_tokens:
            seen_tokens.add(order.token_id)
            snapshot = await OrderBook(session, order.token_id).snapshot()
            depth_events.append({"channel": "pred.depth", **snapshot})
    if cancelled_ids:
        await broadcast_engine_events(depth_events)
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
    snapshot = await OrderBook(session, order.token_id).snapshot()
    await broadcast_engine_events(
        [status_changed, {"channel": "pred.depth", **snapshot}]
    )
    return result
