"""Automated market resolution background worker.

Runs a periodic, idempotent tick across local and community markets:
1. Close ACTIVE markets whose Event.end_date has passed.
2. Propose resolution via deterministic oracle feed for CLOSED markets that
   define ``oracle_feed`` and ``oracle_threshold``.
3. Finalize IN_RESOLUTION markets whose uncontested ``PROPOSED`` dispute
   window has expired. DISPUTED markets remain paused for admin override.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.domain import Event, Market, OracleDispute
from app.services import amm, oracle, settlement

logger = logging.getLogger("app.resolution_worker")

MAX_ORACLE_LAG_SECONDS = 3600.0
_MAX_BACKOFF_SECONDS = 1800.0
# market_id -> (consecutive_failures, next_retry_monotonic)
_oracle_retry_state: dict[str, tuple[int, float]] = {}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def run_resolution_tick(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute one idempotent resolution lifecycle pass."""
    current = _as_utc(now or datetime.now(UTC))
    broadcasts: list[dict[str, Any]] = []
    closed_count = 0
    expired_count = 0
    proposed_count = 0
    finalized_count = 0

    # 0. Expire and refund UNFUNDED markets past Event.end_date
    unfunded_rows = (
        await session.execute(
            select(Market, Event)
            .join(Event, Market.event_id == Event.id)
            .where(Market.status == "UNFUNDED", Event.end_date.is_not(None))
        )
    ).all()
    for market, event in unfunded_rows:
        if event.end_date is not None and _as_utc(event.end_date) <= current:
            await amm.refund_unfunded_market(session, market)
            expired_count += 1
            broadcasts.append(
                {
                    "channel": "pred.status",
                    "market_id": market.id,
                    "status": "EXPIRED",
                }
            )

    # 1. Auto-close expired ACTIVE markets
    active_rows = (
        await session.execute(
            select(Market, Event)
            .join(Event, Market.event_id == Event.id)
            .where(Market.status == "ACTIVE", Event.end_date.is_not(None))
            .with_for_update()
        )
    ).all()
    for market, event in active_rows:
        if event.end_date is not None and _as_utc(event.end_date) <= current:
            market.status = "CLOSED"
            await settlement.cancel_market_orders(session, market.id)
            await settlement.sync_event_status(session, event.id)
            closed_count += 1
            broadcasts.append(
                {
                    "channel": "pred.status",
                    "market_id": market.id,
                    "status": "CLOSED",
                }
            )

    # 2. Auto-propose CLOSED markets with deterministic oracle configuration
    closed_markets = (
        await session.execute(
            select(Market)
            .where(
                Market.status == "CLOSED",
                Market.oracle_feed.is_not(None),
                Market.oracle_threshold.is_not(None),
            )
            .with_for_update()
        )
    ).scalars().all()
    mono_now = time.monotonic()
    for market in closed_markets:
        retry_entry = _oracle_retry_state.get(market.id)
        if retry_entry is not None and mono_now < retry_entry[1]:
            continue
        existing_dispute = (
            await session.execute(
                select(OracleDispute).where(
                    OracleDispute.market_id == market.id,
                    OracleDispute.status.in_(("PROPOSED", "DISPUTED")),
                )
            )
        ).scalar_one_or_none()
        if existing_dispute is not None:
            continue

        ev = (
            await session.execute(select(Event).where(Event.id == market.event_id))
        ).scalar_one_or_none()
        lag_seconds: float | None = None
        at_dt = _as_utc(ev.end_date) if (ev is not None and ev.end_date is not None) else None
        is_gate = (market.oracle_feed or "").lower().startswith("gate:")
        if at_dt is not None:
            lag_seconds = max(0.0, (current - at_dt).total_seconds())
            if lag_seconds > MAX_ORACLE_LAG_SECONDS and not is_gate:
                logger.warning(
                    "skipping stale auto-propose for market %s (lag=%.0fs > %.0fs)",
                    market.id,
                    lag_seconds,
                    MAX_ORACLE_LAG_SECONDS,
                )
                _oracle_retry_state[market.id] = (1, mono_now + _MAX_BACKOFF_SECONDS)
                continue

        try:
            proof = await oracle.evaluate_deterministic_feed(
                market.oracle_feed or "",
                Decimal(str(market.oracle_threshold)),
                comparator=market.oracle_comparator or ">=",
                at_dt=at_dt,
            )
            if lag_seconds is not None:
                proof = {**proof, "lag_seconds": round(lag_seconds, 2)}
            win_idx = int(proof["winning_outcome_index"])
            dispute = await settlement.propose_resolution(session, market, win_idx)
            dispute.proposer_address = f"auto-oracle:{market.oracle_feed}"
            dispute.evidence_json = proof
            _oracle_retry_state.pop(market.id, None)
            proposed_count += 1
            broadcasts.append(
                {
                    "channel": "pred.status",
                    "market_id": market.id,
                    "status": market.status,
                    "proposed_outcome_index": dispute.proposed_outcome_index,
                }
            )
        except Exception:
            fails = (retry_entry[0] if retry_entry else 0) + 1
            delay = min(_MAX_BACKOFF_SECONDS, 30.0 * (2 ** (fails - 1)))
            _oracle_retry_state[market.id] = (fails, mono_now + delay)
            logger.warning(
                "auto-propose failed for market %s (%s); retry in %.0fs",
                market.id,
                market.oracle_feed,
                delay,
                exc_info=True,
            )

    # 3. Auto-finalize uncontested IN_RESOLUTION markets past dispute_deadline
    in_res_markets = (
        await session.execute(
            select(Market).where(Market.status == "IN_RESOLUTION").with_for_update()
        )
    ).scalars().all()
    for market in in_res_markets:
        dispute = (
            await session.execute(
                select(OracleDispute)
                .where(OracleDispute.market_id == market.id)
                .order_by(OracleDispute.created_at.desc())
            )
        ).scalars().first()
        if dispute is None or dispute.status != "PROPOSED":
            continue
        if _as_utc(dispute.dispute_deadline) > current:
            continue
        await settlement.finalize_resolution(
            session, market, int(dispute.proposed_outcome_index)
        )
        finalized_count += 1
        broadcasts.append(
            {
                "channel": "pred.status",
                "market_id": market.id,
                "status": market.status,
                "winning_outcome_index": market.winning_outcome_index,
            }
        )

    return {
        "closed": closed_count,
        "expired": expired_count,
        "proposed": proposed_count,
        "finalized": finalized_count,
        "broadcasts": broadcasts,
    }


async def resolution_worker_loop(interval_seconds: float = 30.0) -> None:
    """Lifespan loop running automated resolution passes."""
    from app.ws.manager import manager

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with AsyncSessionLocal() as session:
                result = await run_resolution_tick(session)
                if result["closed"] or result["expired"] or result["proposed"] or result["finalized"]:
                    await session.commit()
                    for event in result["broadcasts"]:
                        await manager.broadcast(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("resolution worker tick failed")
