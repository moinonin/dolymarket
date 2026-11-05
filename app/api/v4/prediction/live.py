"""Live DexBuilder market data surfaces (read-only, public upstream reads).

These routes proxy the public prediction endpoints of ``api.dexbuilder.com``
without requiring credentials, normalize the payloads into Dolymarket shapes
and serve them from a short-lived cache. They never mutate state and never
expose private (credentialed) upstream data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.live_data import LiveMarketFeed, LiveUnavailableError, get_live_feed

router = APIRouter(prefix="/api/v4/prediction", tags=["prediction-live"])

#: Dolymarket status filters accepted by the live market list.
ALLOWED_STATUSES = {"active", "open", "closed", "resolved", "settled", "historical", ""}


def _unavailable(exc: LiveUnavailableError) -> HTTPException:
    return HTTPException(status_code=502, detail="DEXBUILDER_UPSTREAM_UNAVAILABLE")


@router.get("/live/status")
async def live_status(feed: LiveMarketFeed = Depends(get_live_feed)):
    """Runtime status of the live upstream integration."""
    return feed.status()


@router.get("/live/markets")
async def live_markets(
    status: str | None = Query(default="active"),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live markets straight from DexBuilder.

    ``status`` accepts ``active``, ``closed`` and the ``resolved`` alias;
    ``offset`` walks back through the upstream history.
    """
    if status is not None and str(status).strip().lower() not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(s for s in ALLOWED_STATUSES if s))}",
        )
    try:
        return await feed.markets(
            status=status, category=category, limit=limit, offset=offset
        )
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/markets/{market_id}")
async def live_market(
    market_id: str,
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live market detail (quotes, volume, liquidity, outcomes)."""
    try:
        return await feed.market(market_id)
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/events")
async def live_events(
    limit: int = Query(default=50, ge=1, le=100),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live events straight from DexBuilder."""
    try:
        return await feed.events(limit=limit)
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/tags")
async def live_tags(feed: LiveMarketFeed = Depends(get_live_feed)):
    """Live tag taxonomy."""
    try:
        return await feed.tags()
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/time")
async def live_time(feed: LiveMarketFeed = Depends(get_live_feed)):
    """Upstream server clock (milliseconds since epoch)."""
    try:
        return await feed.time()
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/tokens/{token_id}/order_book")
async def live_order_book(
    token_id: str,
    depth: int = Query(default=50, ge=1, le=200),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live L2 order book for an outcome token."""
    try:
        return await feed.order_book(token_id, depth=depth)
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/tokens/{token_id}/price_history")
async def live_price_history(
    token_id: str,
    interval: str = Query(default="1h"),
    from_ms: int | None = Query(default=None, alias="from"),
    to_ms: int | None = Query(default=None, alias="to"),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live price history (candles) for an outcome token."""
    try:
        return await feed.price_history(
            token_id, interval=interval, from_ms=from_ms, to_ms=to_ms
        )
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/tokens/{token_id}/candlesticks")
async def live_candlesticks(
    token_id: str,
    interval: str = Query(default="1m"),
    limit: int = Query(default=200, ge=1, le=1000),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live OHLCV candlesticks for an outcome token."""
    try:
        return await feed.candlesticks(token_id, interval=interval, limit=limit)
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/live/markets/{market_id}/trades")
async def live_market_trades(
    market_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    feed: LiveMarketFeed = Depends(get_live_feed),
):
    """Live public trade tape for a market."""
    try:
        return await feed.market_trades(market_id, limit=limit)
    except LiveUnavailableError as exc:
        raise _unavailable(exc) from exc
