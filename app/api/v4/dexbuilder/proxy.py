"""DexBuilder proxy: forwards read requests to api.dexbuilder.com."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import User
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
async def proxy_markets(status: str | None = None, category: str | None = None, limit: int = Query(default=50, ge=1, le=100), client: DexBuilderClient = Depends(get_client)):
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
    limit: int = Query(default=50, ge=1, le=200),
    client: DexBuilderClient = Depends(get_client),
):
    try:
        return await client.get_market_trades(market_id, limit=limit)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/events")
async def proxy_events(status: str | None = None, category: str | None = None, limit: int = Query(default=50, ge=1, le=100), client: DexBuilderClient = Depends(get_client)):
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
    limit: int = Query(default=200, ge=1, le=1000),
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

# Private upstream surfaces (positions, settled positions, usertrades, orders) are
# re-exposed here behind authentication. Every request is signed with the
# broker credential and carries X-User-Wallet-Address so the gateway can verify
# the sub-user belongs to this broker.
def _require_wallet(user: User) -> str:
    if not user.dexbuilder_wallet:
        raise HTTPException(
            status_code=400, detail="DEXBUILDER_WALLET_NOT_CONFIGURED"
        )
    return user.dexbuilder_wallet


class DexBuilderOrderRequest(BaseModel):
    token_id: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    price: str = Field(..., min_length=1)
    size: str = Field(..., min_length=1)
    total_cost: str | None = None
    order_type: str = "LIMIT"
    order_mode: str = "GTC"
    client_order_id: str | None = None
    post_only: bool = False
    sell_all: bool = False
    expire_time: int = 0


@router.get("/positions")
async def proxy_positions(
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_positions(user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/positions/settled")
async def proxy_settled_positions(
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_settled_positions(user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/usertrades")
async def proxy_user_trades(
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_user_trades(user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/orders")
async def proxy_orders(
    status: str | None = None,
    condition_id: str | None = None,
    event_id: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_orders(
            user_wallet=wallet,
            status=status,
            condition_id=condition_id,
            event_id=event_id,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.post("/orders")
async def proxy_place_order(
    body: DexBuilderOrderRequest,
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    payload = body.model_dump(exclude_none=True)
    try:
        return await client.place_order(payload, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/orders/{order_id}")
async def proxy_get_order(
    order_id: str,
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_order(order_id, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.delete("/orders/{order_id}")
async def proxy_cancel_order(
    order_id: str,
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.cancel_order(order_id, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.delete("/orders")
async def proxy_cancel_orders_by_condition(
    condition_id: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.cancel_orders_by_condition(condition_id, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/account_book")
async def proxy_account_book(
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_account_book(user_wallet=wallet, limit=limit, cursor=cursor)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/claims/available")
async def proxy_claims_available(
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_claimable(user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.post("/claims")
async def proxy_claim_winnings(
    payload: dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.claim_winnings(payload, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/platform/assets")
async def proxy_platform_assets(client: DexBuilderClient = Depends(get_client)):
    try:
        return await client.get_platform_assets()
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/platform/user")
async def proxy_platform_user(
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_user_info(user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/platform/deposits")
async def proxy_platform_deposits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_deposit_history(user_wallet=wallet, page=page, page_size=page_size)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.get("/platform/withdrawals")
async def proxy_platform_withdrawals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.get_withdraw_history(user_wallet=wallet, page=page, page_size=page_size)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.post("/platform/deposit/sign_data")
async def proxy_platform_deposit_sign_data(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.create_deposit_sign_data(payload, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.post("/platform/withdraw/sign_data")
async def proxy_platform_withdraw_sign_data(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.create_withdraw_sign_data(payload, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc


@router.post("/platform/withdraw/submit")
async def proxy_platform_withdraw_submit(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    client: DexBuilderClient = Depends(get_client),
):
    wallet = _require_wallet(user)
    try:
        return await client.submit_withdraw(payload, user_wallet=wallet)
    except Exception as exc:
        raise _upstream_error(exc) from exc