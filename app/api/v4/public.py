"""Public market discovery endpoints (events, markets, order book, tickers)."""
from datetime import UTC
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.engine.clob import OrderBook
from app.models.domain import Event, Market, OutcomeToken, TradeFill

router = APIRouter(prefix="/api/v4/prediction", tags=["public"])


def _market_payload(m: Market, tokens: list[OutcomeToken] = ()) -> dict:
    return {
        "id": m.id,
        "event_id": m.event_id,
        "condition_id": m.condition_id,
        "question": m.question,
        "outcomes": m.outcomes,
        "tick_size": float(m.tick_size or 0.01),
        "min_order_size": float(m.min_order_size or 5.0),
        "status": m.status,
        "neg_risk": bool(m.neg_risk),
        "winning_outcome_index": m.winning_outcome_index,
        "created_at": str(m.created_at),
        "tokens": [
            {
                "token_id": t.token_id,
                "outcome_index": t.outcome_index,
                "symbol": t.symbol,
            }
            for t in tokens
        ],
    }


def _event_payload(e: Event, markets: list[Market] | None = None) -> dict:
    data = {
        "id": e.id,
        "slug": e.slug,
        "title": e.title,
        "description": e.description,
        "category": e.category,
        "tags": e.tags or [],
        "status": e.status,
        "start_date": str(e.start_date) if e.start_date else None,
        "end_date": str(e.end_date) if e.end_date else None,
        "total_volume": float(e.total_volume or 0),
        "created_at": str(e.created_at),
    }
    if markets is not None:
        data["markets"] = [_market_payload(m) for m in markets]
    return data


async def _tokens_for(session: AsyncSession, market_ids: list[str]) -> dict:
    if not market_ids:
        return {}
    rows = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.market_id.in_(market_ids))
        )
    ).scalars().all()
    grouped: dict[str, list[OutcomeToken]] = {}
    for t in rows:
        grouped.setdefault(t.market_id, []).append(t)
    return grouped


@router.get("/events")
async def list_events(
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    cursor: int | None = 0,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Event)
    if status:
        stmt = stmt.where(Event.status == status.upper())
    if category:
        stmt = stmt.where(Event.category == category)
    if search:
        stmt = stmt.where(
            (Event.title.ilike(f"%{search}%"))
            | (Event.description.ilike(f"%{search}%"))
        )
    if sort_by == "ending_soon":
        stmt = stmt.order_by(Event.end_date.asc().nullslast())
    elif sort_by == "liquidity":
        stmt = stmt.order_by(Event.total_volume.desc())
    else:
        stmt = stmt.order_by(Event.created_at.desc())

    where = stmt.whereclause
    count_stmt = (
        select(func.count()).select_from(Event).where(where) if where is not None
        else select(func.count()).select_from(Event)
    )
    total_count = (await session.execute(count_stmt)).scalar() or 0

    rows = (await session.execute(stmt.offset(cursor or 0).limit(limit))).scalars().all()
    next_cursor = (cursor or 0) + limit if len(rows) == limit else None
    return {
        "events": [_event_payload(e) for e in rows],
        "next_cursor": str(next_cursor) if next_cursor else None,
        "total_count": total_count,
    }


@router.get("/events/{event_id}")
async def get_event(event_id: str, session: AsyncSession = Depends(get_async_session)):
    event = (
        await session.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    markets = (
        await session.execute(select(Market).where(Market.event_id == event.id))
    ).scalars().all()
    token_map = await _tokens_for(session, [m.id for m in markets])
    payload = _event_payload(event, list(markets))
    payload["markets"] = [
        {**_market_payload(m), "tokens": [
            {"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol}
            for t in token_map.get(m.id, [])
        ]}
        for m in markets
    ]
    return payload


@router.get("/events/slug/{slug}")
async def get_event_by_slug(slug: str, session: AsyncSession = Depends(get_async_session)):
    event = (
        await session.execute(select(Event).where(Event.slug == slug))
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    markets = (
        await session.execute(select(Market).where(Market.event_id == event.id))
    ).scalars().all()
    token_map = await _tokens_for(session, [m.id for m in markets])
    payload = _event_payload(event, list(markets))
    payload["markets"] = [
        {**_market_payload(m), "tokens": [
            {"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol}
            for t in token_map.get(m.id, [])
        ]}
        for m in markets
    ]
    return payload


@router.get("/markets")
async def list_markets(
    event_id: str | None = None,
    category: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Market)
    if event_id:
        stmt = stmt.where(Market.event_id == event_id)
    if status:
        stmt = stmt.where(Market.status == status.upper())
    if category:
        stmt = (
            stmt.join(Event, Market.event_id == Event.id).where(Event.category == category)
        )
    markets = (await session.execute(stmt)).scalars().all()
    token_map = await _tokens_for(session, [m.id for m in markets])
    return {
        "markets": [
            {**_market_payload(m), "tokens": [
                {"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol}
                for t in token_map.get(m.id, [])
            ]}
            for m in markets
        ]
    }


@router.get("/markets/{market_id}")
async def get_market(market_id: str, session: AsyncSession = Depends(get_async_session)):
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    tokens = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.market_id == market.id)
        )
    ).scalars().all()
    return _market_payload(market, list(tokens))


async def _token_or_404(session: AsyncSession, token_id: str) -> OutcomeToken:
    token = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.token_id == token_id)
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return token


@router.get("/tokens/{token_id}/order_book")
async def order_book(
    token_id: str,
    depth: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
):
    await _token_or_404(session, token_id)
    book = OrderBook(session, token_id)
    return await book.snapshot(depth)


@router.get("/tokens/{token_id}/price")
@router.get("/tokens/{token_id}/ticker")
async def ticker(token_id: str, session: AsyncSession = Depends(get_async_session)):
    token = await _token_or_404(session, token_id)
    book = OrderBook(session, token.token_id)
    last_fill = (
        await session.execute(
            select(TradeFill)
            .where(TradeFill.token_id == token.token_id)
            .order_by(TradeFill.timestamp.desc())
        )
    ).scalars().first()
    last_price = Decimal(str(last_fill.price)) if last_fill else None
    best_bid = await book.best_bid()
    best_ask = await book.best_ask()
    return {
        "token_id": token.token_id,
        "last_price": float(last_price) if last_price else None,
        "bbo": {
            "best_bid": float(best_bid) if best_bid else None,
            "best_ask": float(best_ask) if best_ask else None,
        },
        "volume_24h": float(
            await _session_volume(session, token.token_id) or 0
        ),
        "high_24h": None if last_fill is None else float(last_fill.price),
        "low_24h": None if last_fill is None else float(last_fill.price),
    }


async def _session_volume(session: AsyncSession, token_id: str) -> Decimal:
    total = 0
    for fill in (
        await session.execute(select(TradeFill).where(TradeFill.token_id == token_id))
    ).scalars():
        total += float(fill.shares) * float(fill.price)
    return Decimal(str(total))


@router.get("/tokens/{token_id}/price_history")
async def price_history(
    token_id: str,
    resolution: str = Query(default="1m"),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_async_session),
):
    await _token_or_404(session, token_id)
    fills = (
        await session.execute(
            select(TradeFill)
            .where(TradeFill.token_id == token_id)
            .order_by(TradeFill.timestamp.asc())
        )
    ).scalars().all()
    candles = []
    if fills:
        candles = _build_candles(list(fills), resolution)
    return {"token_id": token_id, "resolution": resolution, "candles": candles}


def _bucket_seconds(resolution: str) -> int:
    return {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}.get(resolution, 60)


def _build_candles(fills, resolution: str = "1m") -> list[dict]:
    out: dict[int, dict] = {}
    size = _bucket_seconds(resolution)
    for f in fills:
        ts = f.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        epoch = int(ts.timestamp())
        bucket = epoch - (epoch % size)
        p = float(f.price)
        v = float(f.shares)
        c = out.get(bucket)
        if c is None:
            out[bucket] = {"timestamp": bucket, "open": p, "high": p, "low": p, "close": p, "volume": v}
        else:
            c["high"] = max(c["high"], p)
            c["low"] = min(c["low"], p)
            c["close"] = p
            c["volume"] += v
    return [out[k] for k in sorted(out)]
