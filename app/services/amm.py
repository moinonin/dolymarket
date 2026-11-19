"""LMSR Automated Market Maker (AMM) + LP pool service for hybrid liquidity."""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AmmLpPosition, AmmPool, Event, Market, OutcomeToken, Position
from app.services import collateral
from app.services.markets import MIN_COMMUNITY_FUNDING_USDC

logger = logging.getLogger("app.amm")
LN2 = math.log(2.0)


def lmsr_cost(q_yes: float, q_no: float, b: float) -> float:
    """Overflow-safe LMSR cost function C(q) = b * ln(e^(q_yes/b) + e^(q_no/b))."""
    if b <= 0:
        raise ValueError("LMSR depth parameter b must be positive")
    x = q_yes / b
    y = q_no / b
    m = max(x, y)
    return b * (m + math.log(math.exp(x - m) + math.exp(y - m)))


def lmsr_prices(q_yes: float, q_no: float, b: float) -> tuple[Decimal, Decimal]:
    """Marginal YES and NO probabilities (sum to 1.0000)."""
    if b <= 0:
        return Decimal("0.5000"), Decimal("0.5000")
    x = q_yes / b
    y = q_no / b
    m = max(x, y)
    ex = math.exp(x - m)
    ey = math.exp(y - m)
    denom = ex + ey
    p_yes = Decimal(str(round(ex / denom, 4)))
    p_no = (Decimal("1.0000") - p_yes).quantize(Decimal("0.0001"))
    return p_yes, p_no


def quote_amm(
    pool: AmmPool,
    *,
    outcome_index: int,
    side: str,
    shares: Decimal,
) -> dict:
    """Compute exact LMSR notional, fee, avg price, and post-trade marginal prices."""
    if outcome_index not in (0, 1):
        raise HTTPException(status_code=400, detail="AMM supports binary outcomes (index 0 or 1)")
    if shares <= 0:
        raise HTTPException(status_code=400, detail="Shares must be positive")

    qy = float(pool.q_yes)
    qn = float(pool.q_no)
    b = float(pool.b)
    sh = float(shares)
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Side must be BUY or SELL")

    c_before = lmsr_cost(qy, qn, b)
    if side_u == "BUY":
        nq_y = qy + sh if outcome_index == 0 else qy
        nq_n = qn + sh if outcome_index == 1 else qn
        raw_notional = max(0.0, lmsr_cost(nq_y, nq_n, b) - c_before)
    else:
        nq_y = qy - sh if outcome_index == 0 else qy
        nq_n = qn - sh if outcome_index == 1 else qn
        raw_notional = max(0.0, c_before - lmsr_cost(nq_y, nq_n, b))

    notional = collateral.q4(Decimal(str(raw_notional)))
    fee = collateral.q4(notional * Decimal(pool.fee_bps) / Decimal("10000"))
    total_user_usdc = collateral.q4(notional + fee) if side_u == "BUY" else collateral.q4(max(Decimal("0"), notional - fee))
    avg_price = (notional / shares).quantize(Decimal("0.0001"))
    post_yes, post_no = lmsr_prices(nq_y, nq_n, b)

    return {
        "market_id": pool.market_id,
        "outcome_index": outcome_index,
        "side": side_u,
        "shares": float(shares),
        "notional_usdc": float(notional),
        "fee_usdc": float(fee),
        "total_usdc": float(total_user_usdc),
        "avg_price": float(avg_price),
        "post_yes_price": float(post_yes),
        "post_no_price": float(post_no),
    }


async def _debit_available(session: AsyncSession, user_id: str, amount: Decimal, ref: str) -> None:
    account = await collateral.get_or_create_account(session, user_id, for_update=True)
    available = Decimal(str(account.balance)) - Decimal(str(account.locked_balance))
    if amount > available:
        raise HTTPException(status_code=400, detail="Insufficient available balance")
    account.balance = collateral.q4(Decimal(str(account.balance)) - amount)
    await collateral._ledger(session, account, "AMM", -amount, ref)


async def deposit_liquidity(
    session: AsyncSession,
    market: Market,
    user_id: str,
    amount_usdc: Decimal,
) -> AmmPool:
    """Deposit USDC into a market's LMSR pool, mint LP shares, and activate if >= $10."""
    locked_market = (
        await session.execute(
            select(Market).where(Market.id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked_market is not None:
        market = locked_market
    if market.status not in ("UNFUNDED", "ACTIVE"):
        raise HTTPException(status_code=409, detail=f"Cannot fund market in status {market.status}")
    ev = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    if ev is not None and ev.end_date is not None:
        end_dt = ev.end_date if ev.end_date.tzinfo is not None else ev.end_date.replace(tzinfo=UTC)
        if end_dt <= datetime.now(UTC):
            raise HTTPException(status_code=409, detail="Cannot fund an expired market past end_date")
    amount = collateral.q4(amount_usdc)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive")

    # Canonical lock order: Market -> AmmPool -> AmmLpPosition -> CollateralAccount
    pool = (
        await session.execute(
            select(AmmPool).where(AmmPool.market_id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if pool is None:
        b_val = Decimal(str(round(float(amount) / LN2, 6)))
        pool = AmmPool(
            market_id=market.id,
            b=max(Decimal("1.000000"), b_val),
            q_yes=Decimal("0"),
            q_no=Decimal("0"),
            pool_usdc=amount,
            fees_collected_usdc=Decimal("0"),
            total_lp_shares=amount,
        )
        session.add(pool)
        minted_shares = amount
    else:
        existing_usdc = Decimal(str(pool.pool_usdc))
        existing_shares = Decimal(str(pool.total_lp_shares))
        q_y = Decimal(str(pool.q_yes))
        q_n = Decimal(str(pool.q_no))
        worst_liability = max(q_y, q_n)
        net_equity = existing_usdc - worst_liability
        if (q_y > 0 or q_n > 0) and net_equity <= 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot deposit LP into an underwater AMM pool",
            )
        valuation_base = net_equity if net_equity > 0 else existing_usdc
        if valuation_base > 0 and existing_shares > 0:
            minted_shares = collateral.q4(amount * existing_shares / valuation_base)
        else:
            minted_shares = amount
        new_usdc = collateral.q4(existing_usdc + amount)
        pool.pool_usdc = new_usdc
        pool.total_lp_shares = collateral.q4(existing_shares + minted_shares)
        # Only grow b when no open AMM trades exist; otherwise keep b fixed so
        # marginal prices stay invariant without desyncing q_yes/q_no liability.
        if q_y == 0 and q_n == 0:
            pool.b = Decimal(str(round(max(1.0, float(new_usdc) / LN2), 6)))

    lp = (
        await session.execute(
            select(AmmLpPosition)
            .where(AmmLpPosition.market_id == market.id, AmmLpPosition.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    await _debit_available(session, user_id, amount, f"amm_deposit:{market.id}")

    if lp is None:
        lp = AmmLpPosition(
            market_id=market.id,
            user_id=user_id,
            lp_shares=minted_shares,
            deposited_usdc=amount,
        )
        session.add(lp)
    else:
        lp.lp_shares = collateral.q4(Decimal(str(lp.lp_shares)) + minted_shares)
        lp.deposited_usdc = collateral.q4(Decimal(str(lp.deposited_usdc)) + amount)

    market.liquidity_funded_usdc = collateral.q4(
        Decimal(str(getattr(market, "liquidity_funded_usdc", 0) or 0)) + amount
    )
    if market.status == "UNFUNDED" and market.liquidity_funded_usdc >= MIN_COMMUNITY_FUNDING_USDC:
        market.status = "ACTIVE"
        ev = (await session.execute(select(Event).where(Event.id == market.event_id))).scalar_one_or_none()
        if ev is not None and ev.status == "UNFUNDED":
            ev.status = "ACTIVE"

    await session.flush()
    return pool


async def execute_amm_trade(
    session: AsyncSession,
    market: Market,
    token: OutcomeToken,
    user_id: str,
    side: str,
    shares: Decimal,
) -> dict:
    """Execute an instant LMSR trade against the market's AmmPool."""
    if market.status != "ACTIVE":
        raise HTTPException(status_code=409, detail=f"Market is {market.status}; trading requires ACTIVE")
    pool = (
        await session.execute(
            select(AmmPool).where(AmmPool.market_id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if pool is None:
        raise HTTPException(status_code=404, detail="No AMM pool exists for this market")

    sh = collateral.q4(shares)
    q = quote_amm(pool, outcome_index=token.outcome_index, side=side, shares=sh)
    notional = collateral.q4(Decimal(str(q["notional_usdc"])))
    fee = collateral.q4(Decimal(str(q["fee_usdc"])))
    total = collateral.q4(Decimal(str(q["total_usdc"])))

    pos = (
        await session.execute(
            select(Position)
            .where(
                Position.user_id == user_id,
                Position.market_id == market.id,
                Position.token_id == token.token_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if q["side"] == "BUY":
        await _debit_available(session, user_id, total, f"amm_buy:{market.id}")
        if pos is None:
            pos = Position(
                user_id=user_id,
                market_id=market.id,
                token_id=token.token_id,
                shares=sh,
                avg_entry_price=Decimal(str(q["avg_price"])),
            )
            session.add(pos)
        else:
            old_sz = Decimal(str(pos.shares or 0))
            old_avg = Decimal(str(pos.avg_entry_price or 0))
            new_sz = collateral.q4(old_sz + sh)
            pos.avg_entry_price = ((old_sz * old_avg + notional) / new_sz).quantize(Decimal("0.0001"))
            pos.shares = new_sz

        if token.outcome_index == 0:
            pool.q_yes = collateral.q4(Decimal(str(pool.q_yes)) + sh)
        else:
            pool.q_no = collateral.q4(Decimal(str(pool.q_no)) + sh)
        pool.pool_usdc = collateral.q4(Decimal(str(pool.pool_usdc)) + total)
    else:
        avail_shares = Decimal(str(pos.shares or 0)) - Decimal(str(pos.locked_shares or 0)) if pos else Decimal("0")
        if pos is None or avail_shares < sh:
            raise HTTPException(status_code=400, detail="Insufficient outcome shares to sell")
        if total > Decimal(str(pool.pool_usdc)):
            raise HTTPException(status_code=409, detail="AMM pool liquidity insufficient for sell")

        pos.shares = collateral.q4(Decimal(str(pos.shares or 0)) - sh)
        acc = await collateral.get_or_create_account(session, user_id, for_update=True)
        await collateral.credit_payout(session, acc, total, f"amm_sell:{market.id}")

        if token.outcome_index == 0:
            pool.q_yes = collateral.q4(Decimal(str(pool.q_yes)) - sh)
        else:
            pool.q_no = collateral.q4(Decimal(str(pool.q_no)) - sh)
        pool.pool_usdc = collateral.q4(Decimal(str(pool.pool_usdc)) - total)

    lp_fee = collateral.q4(fee * Decimal("0.5"))
    agx_fee = collateral.q4(fee - lp_fee)
    pool.fees_collected_usdc = collateral.q4(Decimal(str(pool.fees_collected_usdc)) + lp_fee)
    if agx_fee > 0:
        try:
            from app.services import agx as agx_service

            if hasattr(session, "begin_nested"):
                async with session.begin_nested():
                    await agx_service.record_fee(
                        session, agx_fee, creator_user_id=market.creator_user_id
                    )
            else:
                await agx_service.record_fee(
                    session, agx_fee, creator_user_id=market.creator_user_id
                )
        except Exception:  # pragma: no cover - AGX accounting must never block AMM trades
            logger.warning("AGX fee accounting failed for market %s", market.id, exc_info=True)
    await session.flush()
    return q


async def redeem_lp(session: AsyncSession, market: Market, user_id: str) -> dict:
    """Redeem LP shares after market is RESOLVED."""
    if market.status != "RESOLVED" or market.winning_outcome_index is None:
        raise HTTPException(status_code=409, detail="LP redemption requires RESOLVED market")

    pool = (
        await session.execute(
            select(AmmPool).where(AmmPool.market_id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if pool is None:
        raise HTTPException(status_code=404, detail="AMM pool not found")

    lp = (
        await session.execute(
            select(AmmLpPosition)
            .where(AmmLpPosition.market_id == market.id, AmmLpPosition.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if lp is None or Decimal(str(lp.lp_shares)) <= 0:
        raise HTTPException(status_code=404, detail="No LP shares to redeem")

    winning_liability = Decimal(str(pool.q_yes if market.winning_outcome_index == 0 else pool.q_no))
    remaining_equity = max(Decimal("0"), Decimal(str(pool.pool_usdc)) - winning_liability)
    total_shares = Decimal(str(pool.total_lp_shares))
    user_shares = Decimal(str(lp.lp_shares))
    payout = collateral.q4(remaining_equity * user_shares / total_shares) if total_shares > 0 else Decimal("0")

    acc = await collateral.get_or_create_account(session, user_id, for_update=True)
    if payout > 0:
        await collateral.credit_payout(session, acc, payout, f"amm_lp_redeem:{market.id}")
    lp.lp_shares = Decimal("0")
    pool.total_lp_shares = collateral.q4(max(Decimal("0"), total_shares - user_shares))
    pool.pool_usdc = collateral.q4(max(Decimal("0"), Decimal(str(pool.pool_usdc)) - payout))
    await session.flush()
    return {"market_id": market.id, "redeemed_shares": float(user_shares), "payout_usdc": float(payout)}


async def refund_unfunded_market(session: AsyncSession, market: Market) -> int:
    """Expire an UNFUNDED market past end_date and refund any partial LP deposits."""
    if market.status != "UNFUNDED":
        return 0
    market.status = "EXPIRED"
    ev = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    if ev is not None and ev.status == "UNFUNDED":
        ev.status = "EXPIRED"

    pool = (
        await session.execute(
            select(AmmPool).where(AmmPool.market_id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if pool is None:
        return 0

    lps = (
        await session.execute(
            select(AmmLpPosition)
            .where(AmmLpPosition.market_id == market.id, AmmLpPosition.lp_shares > 0)
            .with_for_update()
        )
    ).scalars().all()
    refunded = 0
    total_shares = Decimal(str(pool.total_lp_shares))
    pool_usdc = Decimal(str(pool.pool_usdc))
    for lp in lps:
        user_shares = Decimal(str(lp.lp_shares))
        payout = (
            collateral.q4(pool_usdc * user_shares / total_shares)
            if total_shares > 0
            else Decimal("0")
        )
        if payout > 0:
            acc = await collateral.get_or_create_account(
                session, lp.user_id, for_update=True
            )
            await collateral.credit_payout(
                session, acc, payout, f"amm_unfunded_refund:{market.id}"
            )
            refunded += 1
        lp.lp_shares = Decimal("0")
    pool.pool_usdc = Decimal("0")
    pool.total_lp_shares = Decimal("0")
    await session.flush()
    return refunded
