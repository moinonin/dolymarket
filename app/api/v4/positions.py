"""Private position endpoints: portfolio view and redemption claims."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.engine.clob import OrderBook, to_dec
from app.models.domain import (
    Event,
    Market,
    OutcomeToken,
    Position,
    TradeFill,
    User,
)
from app.services import collateral
from app.services import settlement as settlement_service
from app.services.settlement import payout_for_token, redeem_position

router = APIRouter(prefix="/api/v4/prediction", tags=["positions"])


class SplitRequest(BaseModel):
    market_id: str
    shares: float


def _position_payload(p: Position, token: OutcomeToken | None, market: Market | None,
                      event: Event | None, current_price: float | None) -> dict:
    shares = to_dec(p.shares)
    avg = to_dec(p.avg_entry_price)
    cur = Decimal(str(current_price)) if current_price is not None else None
    unrealized = None
    if cur is not None and p.claimed is False:
        unrealized = (cur - avg) * shares
    return {
        "position_id": p.id,
        "user_id": p.user_id,
        "market_id": p.market_id,
        "token_id": p.token_id,
        "outcome_symbol": token.symbol if token else None,
        "market_question": market.question if market else None,
        "event_title": event.title if event else None,
        "event_slug": event.slug if event else None,
        "market_status": market.status if market else None,
        "shares": float(shares),
        "locked_shares": float(to_dec(p.locked_shares)),
        "avg_entry_price": float(avg),
        "current_price": current_price,
        "unrealized_pnl": float(unrealized) if unrealized is not None else None,
        "realized_pnl": float(to_dec(p.realized_pnl)),
        "is_settled": bool(p.is_settled),
        "claimed": bool(p.claimed),
        "updated_at": str(p.updated_at),
    }


async def _current_price(session: AsyncSession, token_id: str) -> float | None:
    fill = (
        await session.execute(
            select(TradeFill)
            .where(TradeFill.token_id == token_id)
            .order_by(TradeFill.timestamp.desc())
        )
    ).scalars().first()
    if fill is not None:
        return float(fill.price)
    book = OrderBook(session, token_id)
    bid = await book.best_bid()
    ask = await book.best_ask()
    if bid is not None and ask is not None:
        return float((bid + ask) / 2)
    return bid and float(bid) or (ask and float(ask)) or None


@router.get("/positions")
async def list_positions(
    settlement_status: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Position).where(Position.user_id == user.id)
    positions = (await session.execute(stmt)).scalars().all()
    out = []
    for p in positions:
        if settlement_status == "OPEN" and (p.is_settled or p.claimed):
            continue
        if settlement_status == "SETTLED":
            market = (
                await session.execute(select(Market).where(Market.id == p.market_id))
            ).scalar_one_or_none()
            if market is None or market.status != "RESOLVED":
                continue
        token = (
            await session.execute(
                select(OutcomeToken).where(OutcomeToken.token_id == p.token_id)
            )
        ).scalar_one_or_none()
        market = (
            await session.execute(select(Market).where(Market.id == p.market_id))
        ).scalar_one_or_none()
        event = (
            await session.execute(select(Event).where(Event.id == (market.event_id if market else None)))
        ).scalar_one_or_none() if market else None
        cur = await _current_price(session, p.token_id)
        out.append(_position_payload(p, token, market, event, cur))
    return {"positions": out}


@router.post("/positions/split")
async def split(
    body: SplitRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    positions = await settlement_service.split_position(
        session, user, market, to_dec(body.shares)
    )
    return {
        "market_id": market.id,
        "shares": body.shares,
        "positions": [
            {"position_id": p.id, "token_id": p.token_id, "shares": float(p.shares)}
            for p in positions
        ],
    }


@router.post("/positions/merge")
async def merge(
    body: SplitRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    collateral_returned = await settlement_service.merge_positions(
        session, user, market, to_dec(body.shares)
    )
    return {
        "market_id": market.id,
        "shares": body.shares,
        "collateral_returned": float(collateral_returned),
    }


def _unused() -> None:  # pragma: no cover
    pass


@router.post("/positions/{position_id}/redeem")
async def redeem(
    position_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    position = (
        await session.execute(select(Position).where(Position.id == position_id))
    ).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your position")

    market = (
        await session.execute(select(Market).where(Market.id == position.market_id))
    ).scalar_one_or_none()
    token = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.token_id == position.token_id)
        )
    ).scalar_one_or_none()

    payout = await redeem_position(session, position)

    account = await collateral.get_or_create_account(session, user.id)
    await collateral.credit_payout(
        session, account, to_dec(payout), reference=position.id
    )

    is_winner = (
        payout > 0
        and market.winning_outcome_index is not None
        and token.outcome_index == market.winning_outcome_index
    )
    return {
        "position_id": position.id,
        "payout_amount": float(payout),
        "status": "SETTLED_CLAIMED",
        "is_winning_token": bool(is_winner),
        "payout_per_share": float(
            await payout_for_token(market, token) if market and token else 0
        ),
    }
