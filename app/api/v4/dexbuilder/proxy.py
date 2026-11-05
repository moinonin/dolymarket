"""DexBuilder proxy: forwards read requests to api.dexbuilder.com."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.dexbuilder import DexBuilderClient, get_config

router = APIRouter(prefix="/api/v4/dexbuilder", tags=["dexbuilder"])


def get_client() -> DexBuilderClient:
    client = DexBuilderClient()
    if not client.enabled:
        raise HTTPException(status_code=503, detail="DEXBUILDER_NOT_CONFIGURED")
    return client


@router.get("/markets")
async def proxy_markets(status: str | None = None, category: str | None = None, limit: int = 50, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_markets(status=status, category=category, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/markets/{market_id}")
async def proxy_market(market_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_market(market_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/markets/slug/{slug}")
async def proxy_market_by_slug(slug: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_market_by_slug(slug)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/events")
async def proxy_events(status: str | None = None, category: str | None = None, limit: int = 50, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_events(status=status, category=category, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/events/{event_id}")
async def proxy_event(event_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_event(event_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/events/slug/{slug}")
async def proxy_event_by_slug(slug: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_event_by_slug(slug)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tags")
async def proxy_tags(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_tags()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tokens/{token_id}/order_book")
async def proxy_order_book(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_order_book(token_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tokens/{token_id}/price")
async def proxy_price(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_price(token_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tokens/{token_id}/ticker")
async def proxy_ticker(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_ticker(token_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tokens/{token_id}/price_history")
async def proxy_price_history(token_id: str, client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_price_history(token_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/tokens/prices")
async def proxy_bulk_prices(ids: str = Query(...), client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_prices([x.strip() for x in ids.split(",") if x.strip()])
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/positions")
async def proxy_positions(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_positions()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/positions/settled")
async def proxy_settled_positions(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_settled_positions()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/usertrades")
async def proxy_user_trades(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_user_trades()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc


@router.get("/orders")
async def proxy_orders(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_orders()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="DEXBUILDER_BAD_RESPONSE") from exc