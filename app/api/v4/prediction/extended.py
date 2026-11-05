"""Extended prediction surfaces: tags, bulk prices, user trades, settled positions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import Event, Market, OutcomeToken, Position, TradeFill, User
from datetime import UTC, datetime

router = APIRouter(prefix="/api/v4/prediction", tags=["prediction-extended"])


@router.get("/tags")
async def list_tags(session: AsyncSession = Depends(get_async_session)):
    events = (await session.execute(select(Event))).scalars().all()
    tags: set[str] = set()
    for e in events:
        for t in (e.tags or []):
            tags.add(str(t))
    return {"tags": sorted(tags)}


@router.get("/markets/slug/{slug}")
async def get_market_by_slug(slug: str, session: AsyncSession = Depends(get_async_session)):
    market = (
        await session.execute(select(Market).where(Market.slug == slug) if hasattr(Market, "slug") else select(Market).where(Market.id == slug))
    ).scalar_one_or_none()
    # Market has no slug column; resolve via event slug -> first market.
    if market is None:
        event = (await session.execute(select(Event).where(Event.slug == slug))).scalar_one_or_none()
        if event is not None:
            market = (await session.execute(select(Market).where(Market.event_id == event.id))).scalars().first()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    tokens = (await session.execute(select(OutcomeToken).where(OutcomeToken.market_id == market.id))).scalars().all()
    return {
        "id": market.id,
        "event_id": market.event_id,
        "question": market.question,
        "outcomes": market.outcomes,
        "status": market.status,
        "tokens": [{"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol} for t in tokens],
    }


@router.get("/tokens/prices")
async def bulk_prices(ids: list[str] = Query(...), session: AsyncSession = Depends(get_async_session)):
    id_list = [x.strip() for s in ids for x in s.split(",") if x.strip()]
    if not id_list:
        raise HTTPException(status_code=422, detail="ids must not be empty")
    out = {}
    for tid in id_list:
        token = (await session.execute(select(OutcomeToken).where(OutcomeToken.token_id == tid))).scalar_one_or_none()
        # price not stored on token; return last trade price if available
        last = (await session.execute(
            select(TradeFill.price).where(TradeFill.token_id == tid).order_by(TradeFill.timestamp.desc())
        )).scalars().first()
        out[tid] = float(last) if last is not None else None
    return {"prices": out}


@router.get("/usertrades")
async def user_trades(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    fills = (
        await session.execute(
            select(TradeFill).where(
                (TradeFill.maker_user_id == user.id) | (TradeFill.taker_user_id == user.id)
            ).order_by(TradeFill.timestamp.desc()).limit(100)
        )
    ).scalars().all()
    return {
        "trades": [
            {
                "id": f.id,
                "market_id": f.market_id,
                "token_id": f.token_id,
                "price": float(f.price),
                "shares": float(f.shares),
                "side": "BUY" if f.taker_user_id == user.id else "SELL",
                "timestamp": str(f.timestamp),
            }
            for f in fills
        ]
    }


@router.get("/positions/settled")
async def settled_positions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    positions = (
        await session.execute(
            select(Position).where(Position.user_id == user.id, Position.is_settled == True)
        )
    ).scalars().all()
    return {
        "positions": [
            {
                "id": p.id,
                "market_id": p.market_id,
                "token_id": p.token_id,
                "shares": float(p.shares),
                "realized_pnl": float(p.realized_pnl),
                "is_settled": p.is_settled,
                "claimed": p.claimed,
            }
            for p in positions
        ]
    }

@router.get("/time")
async def server_time():
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    return {"server_time": now_ms}


@router.get("/markets/{market_id}/trades")
async def market_trades(
    market_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    fills = (
        await session.execute(
            select(TradeFill).where(TradeFill.market_id == market_id)
            .order_by(TradeFill.timestamp.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return {
        "trades": [
            {
                "id": f.id,
                "price": float(f.price),
                "shares": float(f.shares),
                "side": "BUY",
                "timestamp": str(f.timestamp),
            }
            for f in fills
        ]
    }


@router.get("/tokens/{token_id}/market")
async def token_market(token_id: str, session: AsyncSession = Depends(get_async_session)):
    token = (
        await session.execute(select(OutcomeToken).where(OutcomeToken.token_id == token_id))
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    market = (await session.execute(select(Market).where(Market.id == token.market_id))).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    tokens = (await session.execute(select(OutcomeToken).where(OutcomeToken.market_id == market.id))).scalars().all()
    return {
        "id": market.id,
        "event_id": market.event_id,
        "question": market.question,
        "outcomes": market.outcomes,
        "status": market.status,
        "tokens": [{"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol} for t in tokens],
    }


@router.get("/tokens/{token_id}/candlesticks")
async def candlesticks(
    token_id: str,
    interval: str = "1h",
    limit: int = 100,
    session: AsyncSession = Depends(get_async_session),
):
    fills = (
        await session.execute(
            select(TradeFill).where(TradeFill.token_id == token_id)
            .order_by(TradeFill.timestamp.asc())
            .limit(min(limit * 10, 1000))
        )
    ).scalars().all()
    bucket_seconds = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}.get(interval, 3600)
    buckets = {}
    for f in fills:
        ts = f.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        key = int(ts.timestamp()) // bucket_seconds
        buckets.setdefault(key, []).append(f)
    out = []
    for key in sorted(buckets):
        group = buckets[key]
        prices = [float(x.price) for x in group]
        out.append(
            {
                "t": key * bucket_seconds,
                "o": prices[0],
                "h": max(prices),
                "l": min(prices),
                "c": prices[-1],
                "v": sum(float(x.shares) for x in group),
            }
        )
    return {"candlesticks": out[-limit:]}
