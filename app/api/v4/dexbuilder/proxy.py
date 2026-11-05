"""DexBuilder proxy: forwards read requests to api.dexbuilder.com."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.dexbuilder import DexBuilderAuthError, DexBuilderClient

router = APIRouter(prefix="/api/v4/dexbuilder", tags=["dexbuilder"])


def get_client() -> DexBuilderClient:
    client = DexBuilderClient()
    if not client.enabled:
        raise HTTPException(status_code=503, detail="DEXBUILDER_NOT_CONFIGURED")
    return client


def _upstream_error(exc: Exception) -> HTTPException:
    """Map an upstream failure onto the proxy contract.

    A rejected credential is reported separately from a generic bad response
    so the caller can tell "the upstream refused our key" from "the upstream
    answered something unexpected".
    """
    if isinstance(exc, DexBuilderAuthError):
        return HTTPException(
            status_code=502,
            detail="DEXBUILDER_UPSTREAM_UNAUTHORIZED",
            headers={"X-Upstream-Error": exc.label},
        )
    return HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE")


@router.get("/markets")
async def proxy_markets(status: str | None = None, category: str | None = None, limit: int = 50, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_markets(status=status, category=category, limit=limit)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/markets/{market_id}")
async def proxy_market(market_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_market(market_id)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/markets/slug/{slug}")
async def proxy_market_by_slug(slug: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_market_by_slug(slug)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/markets/{market_id}/trades")
async def proxy_market_trades(
    market_id: str,
    limit: int = 50,
    client: DexBuilderClient = Depends(get_client),
):
    try:
        return await client.get_market_trades(market_id, limit=limit)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/events")
async def proxy_events(status: str | None = None, category: str | None = None, limit: int = 50, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_events(status=status, category=category, limit=limit)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/events/{event_id}")
async def proxy_event(event_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_event(event_id)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/events/slug/{slug}")
async def proxy_event_by_slug(slug: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_event_by_slug(slug)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tags")
async def proxy_tags(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_tags()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/{token_id}/order_book")
async def proxy_order_book(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_order_book(token_id)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/{token_id}/price")
async def proxy_price(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_price(token_id)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/{token_id}/ticker")
async def proxy_ticker(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_ticker(token_id)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/{token_id}/price_history")
async def proxy_price_history(
    token_id: str,
    interval: str = "1h",
    from_ms: int | None = Query(default=None, alias="from"),
    to_ms: int | None = Query(default=None, alias="to"),
    client: DexBuilderClient = Depends(get_client),
):
    try:
        return await client.get_price_history(
            token_id, interval=interval, from_ms=from_ms, to_ms=to_ms
        )
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/{token_id}/candlesticks")
async def proxy_candlesticks(
    token_id: str,
    interval: str = "1m",
    limit: int = 200,
    client: DexBuilderClient = Depends(get_client),
):
    try:
        return await client.get_candlesticks(token_id, interval=interval, limit=limit)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/time")
async def proxy_time(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_time()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/tokens/prices")
async def proxy_bulk_prices(
    ids: str | None = Query(default=None),
    token_ids: list[str] | None = Query(default=None),
    client: DexBuilderClient = Depends(get_client),
):
    # Upstream expects repeated `token_ids` params; `ids` accepts a comma
    # separated list for convenience.
    requested: list[str] = []
    if token_ids:
        requested.extend(token_ids)
    if ids:
        requested.extend(part.strip() for part in ids.split(",") if part.strip())
    try:
        return await client.get_prices(requested)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/positions")
async def proxy_positions(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_positions()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/positions/settled")
async def proxy_settled_positions(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_settled_positions()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/usertrades")
async def proxy_user_trades(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_user_trades()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/orders")
async def proxy_orders(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_orders()
    except Exception as exc:
        raise _upstream_error(exc) from exc