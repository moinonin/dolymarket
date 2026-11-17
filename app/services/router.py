"""Atomic CLOB + LMSR AMM Smart Order Router.

Provides unified pre-trade quoting and atomic multi-venue execution across
resting CLOB liquidity and the market's ``AmmPool``. When market makers halt
(e.g. ``ewi >= 0.75`` or pre-expiry), remaining or urgent exit flow routes
seamlessly to ``AmmPool`` in the same database transaction.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.clob import MatchingEngine, OrderBook
from app.models.domain import AmmPool, Market, OutcomeToken
from app.services import amm, collateral
from app.ws.broadcaster import broadcast_engine_events

Q4 = Decimal("0.0001")


def _q4(val: Decimal) -> Decimal:
    return val.quantize(Q4, rounding=ROUND_DOWN)


async def smart_quote(
    session: AsyncSession,
    market: Market,
    token: OutcomeToken,
    side: str,
    shares: Decimal,
    max_slippage_price: Decimal | None = None,
) -> dict[str, Any]:
    """Compute optimal CLOB vs AMM split without mutating state."""
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        raise HTTPException(status_code=422, detail="side must be BUY or SELL")
    sh = _q4(Decimal(str(shares)))
    if sh <= 0:
        raise HTTPException(status_code=422, detail="shares must be positive")

    ob = OrderBook(session, token.token_id)
    bids, asks = await ob.levels(depth=50)
    levels = asks if side_u == "BUY" else bids

    pool = (
        await session.execute(select(AmmPool).where(AmmPool.market_id == market.id))
    ).scalar_one_or_none()
    has_amm = pool is not None and Decimal(str(pool.pool_usdc or 0)) > 0

    amm_spot: Decimal | None = None
    if has_amm and pool is not None:
        p_yes, p_no = amm.lmsr_prices(float(pool.q_yes), float(pool.q_no), float(pool.b))
        amm_spot = p_yes if token.outcome_index == 0 else p_no

    clob_shares = Decimal("0")
    clob_notional = Decimal("0")
    clob_limit_px: Decimal | None = None

    for lvl in levels:
        lvl_px = Decimal(str(lvl[0]))
        lvl_sz = Decimal(str(lvl[1]))
        if lvl_sz <= 0:
            continue
        if max_slippage_price is not None:
            if side_u == "BUY" and lvl_px > max_slippage_price:
                break
            if side_u == "SELL" and lvl_px < max_slippage_price:
                break
        if amm_spot is not None:
            # Only take CLOB levels at least as good as the AMM marginal price.
            if side_u == "BUY" and lvl_px > amm_spot:
                break
            if side_u == "SELL" and lvl_px < amm_spot:
                break

        take = min(sh - clob_shares, lvl_sz)
        if take <= 0:
            break
        clob_shares = _q4(clob_shares + take)
        clob_notional += take * lvl_px
        clob_limit_px = lvl_px
        if clob_shares >= sh:
            break

    remaining = _q4(sh - clob_shares)
    amm_shares = Decimal("0")
    amm_notional = Decimal("0")
    amm_fee = Decimal("0")
    amm_total = Decimal("0")
    amm_avg_price = Decimal("0")

    if remaining > 0 and has_amm and pool is not None:
        q = amm.quote_amm(pool, outcome_index=token.outcome_index, side=side_u, shares=remaining)
        amm_shares = remaining
        amm_notional = Decimal(str(q["notional_usdc"]))
        amm_fee = Decimal(str(q["fee_usdc"]))
        amm_total = Decimal(str(q["total_usdc"]))
        amm_avg_price = Decimal(str(q["avg_price"]))

    total_filled = _q4(clob_shares + amm_shares)
    total_notional = clob_notional + amm_notional
    blended_avg = (total_notional / total_filled).quantize(Q4) if total_filled > 0 else Decimal("0")
    clob_avg = (clob_notional / clob_shares).quantize(Q4) if clob_shares > 0 else Decimal("0")

    return {
        "market_id": market.id,
        "token_id": token.token_id,
        "side": side_u,
        "requested_shares": float(sh),
        "fillable_shares": float(total_filled),
        "has_amm": has_amm,
        "clob_exhausted": remaining > 0,
        "clob_shares": float(clob_shares),
        "clob_avg_price": float(clob_avg),
        "clob_notional_usdc": float(_q4(clob_notional)),
        "clob_limit_price": float(clob_limit_px) if clob_limit_px is not None else None,
        "amm_shares": float(amm_shares),
        "amm_avg_price": float(amm_avg_price),
        "amm_notional_usdc": float(_q4(amm_notional)),
        "amm_fee_usdc": float(_q4(amm_fee)),
        "amm_total_usdc": float(_q4(amm_total)),
        "blended_avg_price": float(blended_avg),
    }


async def execute_smart_order(
    session: AsyncSession,
    user_id: str,
    market: Market,
    token: OutcomeToken,
    side: str,
    shares: Decimal,
    max_slippage_price: Decimal | None = None,
) -> dict[str, Any]:
    """Atomically execute across CLOB (IOC) and LMSR AMM fallback."""
    if market.status != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail=f"Market is {market.status}; trading requires ACTIVE",
        )

    plan = await smart_quote(
        session, market, token, side=side, shares=shares, max_slippage_price=max_slippage_price
    )
    sh = _q4(Decimal(str(shares)))
    clob_target = _q4(Decimal(str(plan["clob_shares"])))
    clob_filled = Decimal("0")
    clob_order_id: str | None = None

    if clob_target > 0 and plan["clob_limit_price"] is not None:
        engine = MatchingEngine(broadcaster=broadcast_engine_events)
        order = await engine.submit_order(
            session=session,
            user_id=user_id,
            market=market,
            token=token,
            collateral_service=collateral,
            side=plan["side"],
            price=Decimal(str(plan["clob_limit_price"])),
            amount=clob_target,
            order_type="LIMIT",
            time_in_force="IOC",
            post_only=False,
        )
        clob_order_id = order.id
        clob_filled = _q4(Decimal(str(order.filled_amount or 0)))

    amm_needed = _q4(sh - clob_filled)
    amm_result: dict[str, Any] | None = None
    amm_filled = Decimal("0")

    if amm_needed > 0 and plan["has_amm"]:
        amm_result = await amm.execute_amm_trade(
            session, market, token, user_id, plan["side"], amm_needed
        )
        amm_filled = amm_needed

    total_filled = _q4(clob_filled + amm_filled)
    if total_filled <= 0:
        raise HTTPException(
            status_code=409,
            detail="No fillable liquidity on CLOB or AMM for requested parameters",
        )

    clob_notional = Decimal(str(plan["clob_avg_price"])) * clob_filled
    amm_notional = Decimal(str(amm_result["notional_usdc"])) if amm_result else Decimal("0")
    blended_avg = ((clob_notional + amm_notional) / total_filled).quantize(Q4)

    return {
        "status": "FILLED" if total_filled >= sh else "PARTIAL",
        "market_id": market.id,
        "token_id": token.token_id,
        "side": plan["side"],
        "requested_shares": float(sh),
        "total_filled_shares": float(total_filled),
        "clob_order_id": clob_order_id,
        "clob_filled_shares": float(clob_filled),
        "amm_filled_shares": float(amm_filled),
        "amm_trade": amm_result,
        "blended_avg_price": float(blended_avg),
    }
