"""Copy (mirror) engine for Pro Desks.

For each desk source fill, evaluates guards, computes the copy size, and places
at most one IOC limit copy order per ACTIVE follower. Exactly-once mirroring
is enforced by a unique constraint on (follower_user_id, source_fill_id).

Money moves only through the existing collateral service (row-level lock,
lock_for_buy, release_lock, charge_fee). No pooled balance, share or NAV.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.engine.clob import MatchingEngine, OrderRejected
from app.engine.fill_queue import FillWriteQueue
from app.models.domain import (
    CopyJob,
    Desk,
    DeskFollower,
    DeskPosition,
    Market,
    Order,
    OutcomeToken,
    Position,
    TradeFill,
)
from app.services import collateral, desk_track_record

Q4 = collateral.Q4


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def q4(value) -> Decimal:
    return collateral.q4(value)


def _env_decimal(key: str, default: str) -> Decimal:
    return Decimal(os.environ.get(key, default).strip() or default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip() or default)
    except ValueError:
        return default


STALENESS_BPS = _env_int("DESK_STALENESS_BPS", 200)
MIN_COPY_RATIO = _env_decimal("DESK_MIN_COPY_RATIO", "0.0100")
MAX_COPY_RATIO = _env_decimal("DESK_MAX_COPY_RATIO", "1.0000")
DEFAULT_COPY_RATIO = _env_decimal("DESK_DEFAULT_COPY_RATIO", "0.2500")
DEFAULT_PER_MARKET_CAP = _env_decimal("DESK_DEFAULT_PER_MARKET_CAP_USDC", "50.0000")
MAX_PER_MARKET_PCT = _env_decimal("DESK_MAX_PER_MARKET_EQUITY_PCT", "20")
MAX_TOTAL_PCT = _env_decimal("DESK_MAX_TOTAL_EQUITY_PCT", "25")
COPY_ENABLED = os.environ.get("COPY_TRADING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def copy_enabled() -> bool:
    return os.environ.get("COPY_TRADING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def size_copy(
    leader_shares,
    copy_ratio,
    price,
    per_market_cap_usdc,
    max_per_market_pct,
    max_total_pct,
    equity_usdc,
    market_exposure_usdc,
    total_exposure_usdc,
    available_usdc,
):
    """Return (budget_usdc, target_shares, limit_breached)."""
    gross_cost = q4(Decimal(str(leader_shares)) * Decimal(str(copy_ratio)))
    per_market_budget = q4(
        min(
            Decimal(str(per_market_cap_usdc)),
            Decimal(str(equity_usdc)) * Decimal(str(max_per_market_pct)) / 100,
        )
    )
    total_budget = q4(Decimal(str(equity_usdc)) * Decimal(str(max_total_pct)) / 100)
    remaining_market = q4(max(Decimal(0), per_market_budget - Decimal(str(market_exposure_usdc))))
    remaining_total = q4(max(Decimal(0), total_budget - Decimal(str(total_exposure_usdc))))
    budget = q4(min(gross_cost, remaining_market, remaining_total, Decimal(str(available_usdc))))
    target_shares = q4(budget / Decimal(str(price))) if Decimal(str(price)) > 0 else Decimal(0)
    limit_breached = budget < gross_cost
    return budget, target_shares, limit_breached


async def _desk_source_fills(session: AsyncSession, desk_id: str) -> list[Order]:
    return []  # placeholder: callers pass fills directly


async def _market_exposure(session: AsyncSession, follower_user_id: str, market_id: str) -> Decimal:
    # Conservative: all of the follower's open copy orders in this market plus
    # their position cost basis in this market.
    total = Decimal(0)
    copy_orders = (
        await session.execute(
            select(Order).where(
                Order.user_id == follower_user_id,
                Order.market_id == market_id,
                Order.copy_source_fill_id.is_not(None),
                Order.status.in_(("OPEN", "PARTIALLY_FILLED")),
            )
        )
    ).scalars().all()
    for o in copy_orders:
        remaining = _dec(o.amount) - _dec(o.filled_amount)
        total += remaining * _dec(o.price)
    positions = (
        await session.execute(
            select(Position).where(
                Position.user_id == follower_user_id,
                Position.market_id == market_id,
            )
        )
    ).scalars().all()
    for p in positions:
        total += _dec(p.shares) * _dec(p.avg_entry_price)
    return q4(total)


async def _total_exposure(session: AsyncSession, follower_user_id: str) -> Decimal:
    total = Decimal(0)
    copy_orders = (
        await session.execute(
            select(Order).where(
                Order.user_id == follower_user_id,
                Order.copy_source_fill_id.is_not(None),
                Order.status.in_(("OPEN", "PARTIALLY_FILLED")),
            )
        )
    ).scalars().all()
    for o in copy_orders:
        remaining = _dec(o.amount) - _dec(o.filled_amount)
        total += remaining * _dec(o.price)
    positions = (
        await session.execute(
            select(Position).where(Position.user_id == follower_user_id)
        )
    ).scalars().all()
    for p in positions:
        total += _dec(p.shares) * _dec(p.avg_entry_price)
    return q4(total)


async def _best_reference(session: AsyncSession, token_id: str, side: str):
    from app.engine.clob import OrderBook

    book = OrderBook(broadcaster=None)
    if side == "BUY":
        return await book.best_ask()
    return await book.best_bid()


async def mirror_source_fill(
    session: AsyncSession,
    desk: Desk,
    source_fill: TradeFill,
    market: Market,
    token: OutcomeToken,
    broadcaster,
) -> list[CopyJob]:
    """Mirror a single desk source fill into each active follower's account."""
    if not copy_enabled():
        return []
    await desk_track_record.maybe_apply_breakers(session, desk)
    if desk.status != "ACTIVE":
        return []

    jobs: list[CopyJob] = []
    followers = (
        await session.execute(
            select(DeskFollower).where(
                DeskFollower.desk_id == desk.id, DeskFollower.status == "ACTIVE"
            )
        )
    ).scalars().all()

    source_price = _dec(source_fill.price)
    source_shares = _dec(source_fill.shares)
    source_side = (
        "BUY"
        if source_fill.taker_user_id == desk.owner_user_id or True
        else "SELL"
    )
    # Determine side from the desk order that produced the fill.
    desk_order = (
        await session.execute(
            select(Order).where(Order.id == source_fill.taker_order_id)
        )
    ).scalar_one_or_none()
    if desk_order is None or desk_order.desk_id != desk.id:
        desk_order = (
            await session.execute(
                select(Order).where(Order.id == source_fill.maker_order_id)
            )
        ).scalar_one_or_none()
    side = desk_order.side if desk_order is not None else "BUY"

    # Update desk position from the source fill.
    await _update_desk_position(session, desk, market, token, source_shares, source_price, side)

    if market.status != "ACTIVE":
        # Still record jobs? No - skip all.
        pass

    for follower in followers:
        if follower.follower_user_id == desk.owner_user_id:
            continue
        # Exactly-once check.
        existing = (
            await session.execute(
                select(CopyJob).where(
                    CopyJob.follower_user_id == follower.follower_user_id,
                    CopyJob.source_fill_id == source_fill.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            jobs.append(existing)
            continue

        job_status = "PENDING"
        error_code = None
        requested_shares = q4(source_shares * _dec(follower.copy_ratio))
        requested_cost = q4(requested_shares * source_price)
        filled_shares = Decimal(0)
        filled_cost = Decimal(0)
        limit_breached = False

        # Market closed?
        if market.status != "ACTIVE":
            job_status = "SKIPPED_MARKET_CLOSED"
            _persist_job(session, desk, follower, source_fill, job_status, follower.copy_ratio,
                         requested_shares, requested_cost, filled_shares, filled_cost,
                         limit_breached, error_code)
            continue

        # Reference quote + staleness
        ref = await _best_reference(session, token.token_id, side)
        if ref is None:
            job_status = "SKIPPED_NO_LIQUIDITY"
            _persist_job(session, desk, follower, source_fill, job_status, follower.copy_ratio,
                         requested_shares, requested_cost, filled_shares, filled_cost,
                         limit_breached, error_code)
            continue
        ref_dec = _dec(ref)
        if ref_dec > 0:
            bps = abs(source_price - ref_dec) / ref_dec * Decimal(10000)
            if bps > Decimal(STALENESS_BPS):
                job_status = "SKIPPED_STALE"
                _persist_job(session, desk, follower, source_fill, job_status, follower.copy_ratio,
                             requested_shares, requested_cost, filled_shares, filled_cost,
                             limit_breached, error_code)
                continue

        # Sizing
        account = await collateral.get_or_create_account(session, follower.follower_user_id)
        equity = _dec(account.balance) + _dec(account.locked_balance)
        available = _dec(account.balance) - _dec(account.locked_balance)
        me = await _market_exposure(session, follower.follower_user_id, market.id)
        te = await _total_exposure(session, follower.follower_user_id)
        budget, target_shares, lb = size_copy(
            source_shares,
            follower.copy_ratio,
            source_price,
            follower.per_market_cap_usdc,
            follower.max_per_market_pct,
            follower.max_total_pct,
            equity,
            me,
            te,
            available,
        )
        limit_breached = lb
        requested_shares = target_shares
        requested_cost = budget

        min_size = _dec(market.min_order_size)
        if target_shares < min_size:
            if available < min_size * source_price:
                job_status = "SKIPPED_INSUFFICIENT_FUNDS"
            else:
                job_status = "SKIPPED_LIMIT_BREACHED"
            _persist_job(session, desk, follower, source_fill, job_status, follower.copy_ratio,
                         requested_shares, requested_cost, filled_shares, filled_cost,
                         limit_breached, error_code)
            continue

        # Place the copy order.
        engine = MatchingEngine(broadcaster=None)
        try:
            order = await engine.submit_order(
                session,
                follower.follower_user_id,
                market,
                token,
                collateral,
                side=side,
                price=source_price,
                amount=target_shares,
                order_type="LIMIT",
                time_in_force="IOC",
                post_only=False,
                desk_id=None,
                copy_source_fill_id=source_fill.id,
            )
            filled_shares = _dec(order.filled_amount)
            filled_cost = q4(filled_shares * source_price)
            if filled_shares >= target_shares:
                job_status = "FILLED"
            elif filled_shares > 0:
                job_status = "PARTIALLY_FILLED"
            else:
                job_status = "SKIPPED_NO_LIQUIDITY"
        except OrderRejected as exc:
            job_status = "FAILED"
            error_code = exc.detail
        except Exception as exc:  # pragma: no cover - defensive
            job_status = "FAILED"
            error_code = str(exc)

        job = _persist_job(
            session,
            desk,
            follower,
            source_fill,
            job_status,
            follower.copy_ratio,
            requested_shares,
            requested_cost,
            filled_shares,
            filled_cost,
            limit_breached,
            error_code,
        )
        jobs.append(job)

    await session.flush()
    return jobs


def _persist_job(
    session,
    desk,
    follower,
    source_fill,
    status,
    copy_ratio,
    requested_shares,
    requested_cost,
    filled_shares,
    filled_cost,
    limit_breached,
    error_code,
):
    job = CopyJob(
        desk_id=desk.id,
        follower_user_id=follower.follower_user_id,
        source_fill_id=source_fill.id,
        status=status,
        copy_ratio=q4(copy_ratio),
        requested_shares=q4(requested_shares),
        requested_cost_usdc=q4(requested_cost),
        filled_shares=q4(filled_shares),
        filled_cost_usdc=q4(filled_cost),
        limit_breached=bool(limit_breached),
        error_code=error_code,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        # Exactly-once: another run won the race; fetch it.
        session.rollback()
        existing = (
            session.execute(
                select(CopyJob).where(
                    CopyJob.follower_user_id == follower.follower_user_id,
                    CopyJob.source_fill_id == source_fill.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise
    return job


async def _update_desk_position(session, desk, market, token, shares, price, side):
    pos = (
        await session.execute(
            select(DeskPosition).where(
                DeskPosition.desk_id == desk.id, DeskPosition.token_id == token.token_id
            )
        )
    ).scalar_one_or_none()
    if pos is None:
        pos = DeskPosition(
            desk_id=desk.id,
            market_id=market.id,
            token_id=token.token_id,
            outcome_index=token.outcome_index,
            shares=0,
            avg_entry_price=0,
            realized_pnl_usdc=0,
        )
        session.add(pos)
        await session.flush()
    delta = shares if side == "BUY" else -shares
    new_shares = _dec(pos.shares) + delta
    if delta > 0:
        old = _dec(pos.shares)
        old_avg = _dec(pos.avg_entry_price)
        total = old + shares
        pos.avg_entry_price = (
            (old * old_avg + shares * price) / total if total > 0 else price
        )
    else:
        avg = _dec(pos.avg_entry_price)
        pos.realized_pnl_usdc = _dec(pos.realized_pnl_usdc) + (price - avg) * (-delta)
    if side == "SELL":
        pass
    pos.shares = max(Decimal(0), new_shares)
    pos.outcome_index = token.outcome_index
    pos.updated_at = datetime.now(UTC)
    await session.flush()
    return pos


async def update_desk_position_on_fill(session, desk_id, market_id, token_id, outcome_index, shares, price, side):
    # convenience for external callers
    pass