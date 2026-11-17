"""Hybrid LMSR AMM API routes (pool state, quote, LP deposit, trade, redeem)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import AmmPool, Market, OutcomeToken, User
from app.services import amm

router = APIRouter(prefix="/api/v4/prediction/amm", tags=["amm"])


class AmmDepositRequest(BaseModel):
    amount_usdc: Decimal = Field(gt=Decimal("0"), le=Decimal("100000"))

    @field_validator("amount_usdc")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be finite")
        return v


class AmmTradeRequest(BaseModel):
    token_id: str = Field(min_length=1, max_length=100)
    side: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    shares: Decimal = Field(gt=Decimal("0"), le=Decimal("1000000"))

    @field_validator("shares")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be finite")
        return v


@router.get("/{market_id}")
async def get_amm_pool(
    market_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    pool = (
        await session.execute(select(AmmPool).where(AmmPool.market_id == market_id))
    ).scalar_one_or_none()
    if pool is None:
        raise HTTPException(status_code=404, detail="AMM pool not found")
    p_yes, p_no = amm.lmsr_prices(float(pool.q_yes), float(pool.q_no), float(pool.b))
    return {
        "market_id": pool.market_id,
        "b": float(pool.b),
        "q_yes": float(pool.q_yes),
        "q_no": float(pool.q_no),
        "pool_usdc": float(pool.pool_usdc),
        "fees_collected_usdc": float(pool.fees_collected_usdc),
        "total_lp_shares": float(pool.total_lp_shares),
        "fee_bps": pool.fee_bps,
        "yes_price": float(p_yes),
        "no_price": float(p_no),
    }


@router.get("/{market_id}/quote")
async def quote_amm_trade(
    market_id: str,
    outcome_index: int = Query(default=0, ge=0, le=1),
    side: str = Query(default="BUY"),
    shares: Decimal = Query(gt=Decimal("0"), le=Decimal("1000000")),
    session: AsyncSession = Depends(get_async_session),
):
    pool = (
        await session.execute(select(AmmPool).where(AmmPool.market_id == market_id))
    ).scalar_one_or_none()
    if pool is None:
        raise HTTPException(status_code=404, detail="AMM pool not found")
    return amm.quote_amm(pool, outcome_index=outcome_index, side=side, shares=shares)


@router.post("/{market_id}/deposit")
async def deposit_amm_liquidity(
    market_id: str,
    body: AmmDepositRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    if getattr(market, "tier", "OFFICIAL") != "COMMUNITY" and not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=403,
            detail="Only COMMUNITY markets or admins can deposit AMM liquidity",
        )
    pool = await amm.deposit_liquidity(session, market, user.id, body.amount_usdc)
    p_yes, p_no = amm.lmsr_prices(float(pool.q_yes), float(pool.q_no), float(pool.b))
    return {
        "market_id": market.id,
        "market_status": market.status,
        "pool_usdc": float(pool.pool_usdc),
        "total_lp_shares": float(pool.total_lp_shares),
        "yes_price": float(p_yes),
        "no_price": float(p_no),
    }


@router.post("/{market_id}/trade")
async def trade_amm(
    market_id: str,
    body: AmmTradeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    token = (
        await session.execute(
            select(OutcomeToken).where(
                OutcomeToken.market_id == market.id, OutcomeToken.token_id == body.token_id
            )
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Outcome token not found")
    return await amm.execute_amm_trade(session, market, token, user.id, body.side, body.shares)


@router.post("/{market_id}/redeem")
async def redeem_amm_lp(
    market_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    return await amm.redeem_lp(session, market, user.id)
