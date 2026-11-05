"""Deterministic track-record calculation for Pro Desks.

Every value is computed from stored source fills and settled desk positions.
Money values use Decimal (Numeric(18,4) in the DB); no floating point.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.domain import CopyJob, Desk, DeskFollower, DeskPosition, Market, Order, TradeFill

Q4 = Decimal("0.0001")


def q4(value) -> Decimal:
    return Decimal(str(value)).quantize(Q4, rounding=ROUND_DOWN)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _desk_breaker_pct() -> Decimal:
    return Decimal(os.environ.get("DESK_DRAWDOWN_BREAKER_PCT", "20"))


async def _desk_source_fills(session: AsyncSession, desk_id: str) -> list[TradeFill]:
    desk_order_ids = (
        await session.execute(select(Order.id).where(Order.desk_id == desk_id))
    ).scalars().all()
    desk_order_set = set(desk_order_ids)
    if not desk_order_set:
        return []
    fills = (
        await session.execute(
            select(TradeFill).where(
                (TradeFill.maker_order_id.in_(desk_order_set))
                | (TradeFill.taker_order_id.in_(desk_order_set))
            )
        )
    ).scalars().all()
    return [f for f in fills if f.maker_order_id in desk_order_set or f.taker_order_id in desk_order_set]


async def _source_fill_fees(session: AsyncSession, desk_id: str) -> Decimal:
    desk_order_ids = set(
        (await session.execute(select(Order.id).where(Order.desk_id == desk_id))).scalars().all()
    )
    fills = await _desk_source_fills(session, desk_id)
    total = Decimal(0)
    for f in fills:
        if f.maker_order_id in desk_order_ids:
            total += _dec(f.maker_fee)
        if f.taker_order_id in desk_order_ids:
            total += _dec(f.taker_fee)
    return q4(total)


async def compute_track_record(session: AsyncSession, desk_id: str) -> dict:
    """Return the deterministic track-record for a desk."""
    desk = (await session.execute(select(Desk).where(Desk.id == desk_id))).scalar_one_or_none()
    if desk is None:
        return _empty_record()

    settled = (
        await session.execute(
            select(DeskPosition).where(
                DeskPosition.desk_id == desk_id,
                DeskPosition.settled_at.is_not(None),
            )
        )
    ).scalars().all()

    cost_basis = Decimal(0)
    payout = Decimal(0)
    winning = 0
    realized = Decimal(0)
    for pos in settled:
        market = (
            await session.execute(select(Market).where(Market.id == pos.market_id))
        ).scalar_one_or_none()
        winning_outcome = getattr(market, "winning_outcome_index", None) if market else None
        pos_cost = _dec(pos.shares) * _dec(pos.avg_entry_price)
        cost_basis += pos_cost
        if winning_outcome is not None and int(pos.outcome_index) == int(winning_outcome):
            payout += _dec(pos.shares) * Decimal("1.0000")
            winning += 1
        realized += _dec(pos.realized_pnl_usdc)

    fees_paid = await _source_fill_fees(session, desk_id)
    net_pnl = (payout - cost_basis) - fees_paid

    closed = len(settled)
    win_rate = (Decimal(winning) / Decimal(closed)) if closed else Decimal(0)

    # avg win / loss over settled positions (realized pnl)
    wins = [_dec(p.realized_pnl_usdc) for p in settled if _dec(p.realized_pnl_usdc) > 0]
    losses = [_dec(p.realized_pnl_usdc) for p in settled if _dec(p.realized_pnl_usdc) < 0]
    avg_win = (sum(wins, Decimal(0)) / Decimal(len(wins))) if wins else Decimal(0)
    avg_loss = (sum(losses, Decimal(0)) / Decimal(len(losses))) if losses else Decimal(0)

    # max drawdown on realized pnl curve (fees excluded)
    ordered = sorted(settled, key=lambda p: (p.settled_at or datetime.now(UTC), p.id))
    peak = Decimal(0)
    running = Decimal(0)
    max_dd = Decimal(0)
    for pos in ordered:
        running += _dec(pos.realized_pnl_usdc)
        if running > peak:
            peak = running
        if peak > 0:
            dd = (peak - running) / peak * Decimal(100)
            if dd > max_dd:
                max_dd = dd

    # rolling 30-day drawdown
    cutoff = datetime.now(UTC) - timedelta(days=30)
    recent = [p for p in ordered if (p.settled_at is None or _ensure_aware(p.settled_at) >= cutoff)]
    peak = Decimal(0)
    running = Decimal(0)
    rolling_dd = Decimal(0)
    for pos in recent:
        running += _dec(pos.realized_pnl_usdc)
        if running > peak:
            peak = running
        if peak > 0:
            dd = (peak - running) / peak * Decimal(100)
            if dd > rolling_dd:
                rolling_dd = dd

    # follower + copy counts
    source_fills = await _desk_source_fills(session, desk_id)
    first_fill_at = min((f.timestamp for f in source_fills), default=None)
    if first_fill_at is not None:
        first_fill_at = _ensure_aware(first_fill_at)
        days_active = max(0, (datetime.now(UTC) - first_fill_at).days)
    else:
        days_active = 0

    active_followers = (
        await session.execute(
            select(DeskFollower).where(
                DeskFollower.desk_id == desk_id, DeskFollower.status == "ACTIVE"
            )
        )
    ).scalars().all()
    copy_jobs = (
        await session.execute(
            select(CopyJob).where(CopyJob.desk_id == desk_id, CopyJob.status.in_(("FILLED", "PARTIALLY_FILLED")))
        )
    ).scalars().all()

    roi_pct = (net_pnl / max(cost_basis, Decimal("0.0100"))) * Decimal(100)

    curve = []
    cum = Decimal(0)
    for pos in ordered:
        cum += _dec(pos.realized_pnl_usdc)
        curve.append(
            {
                "settled_at": str(pos.settled_at),
                "realized_pnl_usdc": float(q4(_dec(pos.realized_pnl_usdc))),
                "cumulative_usdc": float(q4(cum)),
            }
        )

    return {
        "desk_id": desk.id,
        "status": desk.status,
        "name": desk.name,
        "slug": desk.slug,
        "description": desk.description,
        "active_follower_count": len(active_followers),
        "copied_fill_count": len(copy_jobs),
        "days_active": days_active,
        "closed_positions": closed,
        "winning_positions": winning,
        "cost_basis_usdc": q4(cost_basis),
        "payout_usdc": q4(payout),
        "realized_pnl_usdc": q4(realized),
        "fees_paid_usdc": q4(fees_paid),
        "net_pnl_usdc": q4(net_pnl),
        "win_rate": q4(win_rate),
        "roi_pct": q4(roi_pct),
        "avg_win_usdc": q4(avg_win),
        "avg_loss_usdc": q4(avg_loss),
        "max_drawdown_pct": q4(max_dd),
        "rolling_drawdown_30d_pct": q4(rolling_dd),
        "curve": curve,
    }


def _empty_record() -> dict:
    return {
        "desk_id": None,
        "status": None,
        "name": None,
        "slug": None,
        "description": None,
        "active_follower_count": 0,
        "copied_fill_count": 0,
        "days_active": 0,
        "closed_positions": 0,
        "winning_positions": 0,
        "cost_basis_usdc": q4(0),
        "payout_usdc": q4(0),
        "realized_pnl_usdc": q4(0),
        "fees_paid_usdc": q4(0),
        "net_pnl_usdc": q4(0),
        "win_rate": q4(0),
        "roi_pct": q4(0),
        "avg_win_usdc": q4(0),
        "avg_loss_usdc": q4(0),
        "max_drawdown_pct": q4(0),
        "rolling_drawdown_30d_pct": q4(0),
        "curve": [],
    }


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def maybe_apply_breakers(session: AsyncSession, desk: Desk) -> None:
    """Evaluate the automatic suspension triggers; mutate desk state in place."""
    rec = await compute_track_record(session, desk.id)
    if rec["closed_positions"] <= 0:
        return
    if rec["rolling_drawdown_30d_pct"] >= _desk_breaker_pct():
        if desk.status == "ACTIVE":
            desk.status = "SUSPENDED"
            desk.review_note = "DRAWDOWN_BREAKER"
            desk.suspended_at = datetime.now(UTC)


async def ensure_enabled() -> None:
    import os
    if os.environ.get("COPY_TRADING_ENABLED", "true").strip().lower() not in ("1", "true", "yes", "on"):
        raise PermissionError("disabled")