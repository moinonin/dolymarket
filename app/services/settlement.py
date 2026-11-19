"""Conditional Tokens Framework (CTF) settlement and oracle resolution.

Implements the UMA optimistic oracle pattern: bonded proposal, dispute
counter-bond with a simulated challenge window, and atomic 1:1 payout of
winning outcome tokens ($1.00 USDC per share; losing shares pay $0.00).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Event, Market, OracleDispute, OutcomeToken, Position, User
from app.services.markets import ensure_market_open_for_trading

DISPUTE_WINDOW = timedelta(hours=2)
PROPOSAL_BOND = Decimal(50)
MIN_DISPUTE_BOND = Decimal("100")
INVALID_OUTCOME_INDEX = -1


def compute_rules_hash(market: Market, event: Event | None = None) -> str:
    """Compute deterministic SHA-256 hash of market rules (Polymarket ancillaryData parity)."""
    end_iso = None
    if event is not None and event.end_date is not None:
        end_dt = (
            event.end_date
            if event.end_date.tzinfo is not None
            else event.end_date.replace(tzinfo=UTC)
        )
        end_iso = end_dt.astimezone(UTC).isoformat()
    payload = {
        "question": (market.question or "").strip(),
        "resolution_criteria": (market.resolution_criteria or "").strip(),
        "outcomes": list(market.outcomes or []),
        "end_date": end_iso,
        "oracle_feed": market.oracle_feed,
        "oracle_threshold": (
            str(market.oracle_threshold) if market.oracle_threshold is not None else None
        ),
        "oracle_comparator": market.oracle_comparator,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "0x" + hashlib.sha256(canonical).hexdigest()


def _append_audit_update(
    dispute: OracleDispute,
    event_name: str,
    *,
    outcome_index: int | None = None,
    actor: str | None = None,
    note: str | None = None,
    extra: dict | None = None,
) -> None:
    """Append an immutable state-transition entry to dispute.evidence_json['updates']."""
    ev = dict(dispute.evidence_json) if isinstance(dispute.evidence_json, dict) else {}
    updates = list(ev.get("updates") or [])
    entry: dict = {
        "event": event_name,
        "timestamp": _now().isoformat(),
    }
    if outcome_index is not None:
        entry["outcome_index"] = outcome_index
    if actor:
        entry["actor"] = actor
    if note:
        entry["note"] = note
    updates.append(entry)
    ev["updates"] = updates
    if extra:
        ev.update(extra)
    dispute.evidence_json = ev


def _now() -> datetime:
    return datetime.now(UTC)


async def cancel_market_orders(session: AsyncSession, market_id: str) -> int:
    """Cancel all resting OPEN/PARTIALLY_FILLED orders for a market and release locks."""
    from app.engine.clob import MatchingEngine
    from app.models.domain import Order
    from app.services import collateral

    orders = (
        await session.execute(
            select(Order).where(
                Order.market_id == market_id,
                Order.status.in_(("OPEN", "PARTIALLY_FILLED")),
            )
        )
    ).scalars().all()
    if not orders:
        return 0
    engine = MatchingEngine()
    for order in orders:
        await engine.cancel_order(session, order, collateral)
    return len(orders)


async def sync_event_status(session: AsyncSession, event_id: str) -> None:
    """Update parent Event status only when all sibling markets have transitioned."""
    event = (
        await session.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        return
    statuses = (
        await session.execute(select(Market.status).where(Market.event_id == event_id))
    ).scalars().all()
    if not statuses or any(s == "ACTIVE" for s in statuses):
        return
    if all(s == "RESOLVED" for s in statuses):
        event.status = "RESOLVED"
    elif all(s in ("CLOSED", "IN_RESOLUTION", "DISPUTED", "RESOLVED", "EXPIRED") for s in statuses):
        event.status = "CLOSED"


async def propose_resolution(
    session: AsyncSession,
    market: Market,
    proposed_outcome_index: int,
    *,
    source_url: str | None = None,
    evidence_text: str | None = None,
) -> OracleDispute:
    if market.status not in ("CLOSED",):
        raise HTTPException(
            status_code=409,
            detail=f"Market must be CLOSED to propose resolution (current: {market.status})",
        )
    if proposed_outcome_index < 0 or proposed_outcome_index >= len(market.outcomes or []):
        raise HTTPException(status_code=422, detail="Invalid proposed outcome index")
    if source_url or evidence_text:
        from app.services.oracle_verifier import verify_resolution_evidence

        outcome_label = str((market.outcomes or [])[proposed_outcome_index])
        verdict = await verify_resolution_evidence(
            market.question,
            outcome_label,
            source_url=source_url,
            evidence_text=evidence_text,
            resolution_criteria=market.resolution_criteria,
            oracle_threshold=(
                float(market.oracle_threshold) if market.oracle_threshold is not None else None
            ),
            oracle_comparator=market.oracle_comparator,
        )
        if verdict["verdict"] == "CONTRADICTS" and float(verdict["confidence"]) >= 0.85:
            raise HTTPException(
                status_code=422,
                detail="Submitted evidence contradicts proposed outcome",
            )
    existing = (
        await session.execute(
            select(OracleDispute).where(
                OracleDispute.market_id == market.id,
                OracleDispute.status.in_(("PROPOSED", "DISPUTED")),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Resolution already proposed")

    event = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    rules_hash = compute_rules_hash(market, event)

    dispute = OracleDispute(
        market_id=market.id,
        proposed_outcome_index=proposed_outcome_index,
        proposer_address="uma-optimistic-oracle",
        bond_amount=PROPOSAL_BOND,
        dispute_deadline=_now() + DISPUTE_WINDOW,
        status="PROPOSED",
        evidence_json={
            "rules_hash": rules_hash,
            "was_disputed": False,
            "reproposed_outcome_index": None,
            "updates": [
                {
                    "event": "PROPOSED",
                    "outcome_index": proposed_outcome_index,
                    "actor": "uma-optimistic-oracle",
                    "timestamp": _now().isoformat(),
                }
            ],
        },
    )
    session.add(dispute)
    market.status = "IN_RESOLUTION"
    await sync_event_status(session, market.event_id)
    return dispute


async def dispute_proposal(
    session: AsyncSession, market: Market, counter_bond: Decimal
) -> OracleDispute:
    locked_market = (
        await session.execute(
            select(Market).where(Market.id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked_market is not None:
        market = locked_market
    dispute = (
        await session.execute(
            select(OracleDispute)
            .where(
                OracleDispute.market_id == market.id,
                OracleDispute.status.in_(("PROPOSED",)),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if dispute is None:
        raise HTTPException(status_code=404, detail="No pending resolution proposal")
    if market.status != "IN_RESOLUTION":
        raise HTTPException(status_code=409, detail="Market is not IN_RESOLUTION")
    # SQLite drops the tzinfo on the way through a timezone-aware column;
    # normalise before comparing so an aware _now() never raises against a
    # naive stored deadline.
    deadline = dispute.dispute_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if _now() > deadline:
        raise HTTPException(status_code=409, detail="Dispute window has expired")
    min_required = max(MIN_DISPUTE_BOND, Decimal(str(dispute.bond_amount)))
    if counter_bond < min_required:
        raise HTTPException(
            status_code=400,
            detail=f"Counter-bond below minimum required ({min_required} AGX)",
        )
    dispute.status = "DISPUTED"
    market.status = "DISPUTED"
    _append_audit_update(
        dispute,
        "DISPUTED",
        outcome_index=dispute.proposed_outcome_index,
        note=f"counter_bond={counter_bond}",
        extra={"was_disputed": True},
    )
    return dispute


async def repropose_resolution(
    session: AsyncSession,
    market: Market,
    reproposed_outcome_index: int,
    *,
    actor: str = "admin",
    source_url: str | None = None,
    evidence_text: str | None = None,
    note: str | None = None,
) -> OracleDispute:
    """Polymarket-style single re-proposal after a first dispute.

    Allows correcting a disputed proposal once with a fresh 2-hour challenge window.
    A second dispute cannot be reproposed and must be finalized directly.
    """
    locked_market = (
        await session.execute(
            select(Market).where(Market.id == market.id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked_market is not None:
        market = locked_market
    if market.status != "DISPUTED":
        raise HTTPException(
            status_code=409,
            detail=f"Market must be DISPUTED to repropose (current: {market.status})",
        )
    if reproposed_outcome_index < 0 or reproposed_outcome_index >= len(market.outcomes or []):
        raise HTTPException(status_code=422, detail="Invalid reproposed outcome index")

    dispute = (
        await session.execute(
            select(OracleDispute)
            .where(
                OracleDispute.market_id == market.id,
                OracleDispute.status == "DISPUTED",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if dispute is None:
        raise HTTPException(status_code=404, detail="No disputed resolution found")

    ev_meta = dispute.evidence_json if isinstance(dispute.evidence_json, dict) else {}
    if ev_meta.get("reproposed_outcome_index") is not None:
        raise HTTPException(
            status_code=409,
            detail="Resolution was already reproposed once; finalize directly",
        )

    if source_url or evidence_text:
        from app.services.oracle_verifier import verify_resolution_evidence

        outcome_label = str((market.outcomes or [])[reproposed_outcome_index])
        verdict = await verify_resolution_evidence(
            market.question,
            outcome_label,
            source_url=source_url,
            evidence_text=evidence_text,
            resolution_criteria=market.resolution_criteria,
            oracle_threshold=(
                float(market.oracle_threshold) if market.oracle_threshold is not None else None
            ),
            oracle_comparator=market.oracle_comparator,
        )
        if verdict["verdict"] == "CONTRADICTS" and float(verdict["confidence"]) >= 0.85:
            raise HTTPException(
                status_code=422,
                detail="Submitted evidence contradicts reproposed outcome",
            )

    dispute.proposed_outcome_index = reproposed_outcome_index
    dispute.status = "PROPOSED"
    dispute.dispute_deadline = _now() + DISPUTE_WINDOW
    market.status = "IN_RESOLUTION"
    extra: dict = {"reproposed_outcome_index": reproposed_outcome_index}
    if source_url:
        extra["repropose_source_url"] = source_url
    if evidence_text:
        extra["repropose_evidence_text"] = evidence_text
    _append_audit_update(
        dispute,
        "REPROPOSED",
        outcome_index=reproposed_outcome_index,
        actor=actor,
        note=note,
        extra=extra,
    )
    await sync_event_status(session, market.event_id)
    return dispute


async def finalize_resolution(
    session: AsyncSession,
    market: Market,
    winning_outcome_index: int,
    *,
    resolve_invalid: bool = False,
) -> Market:
    if market.status not in ("IN_RESOLUTION", "DISPUTED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resolve market in status {market.status}",
        )
    if resolve_invalid or winning_outcome_index == INVALID_OUTCOME_INDEX:
        effective_idx = INVALID_OUTCOME_INDEX
    else:
        if winning_outcome_index < 0 or winning_outcome_index >= len(market.outcomes or []):
            raise HTTPException(status_code=422, detail="Invalid winning outcome index")
        effective_idx = winning_outcome_index

    market.winning_outcome_index = effective_idx
    market.status = "RESOLVED"
    await sync_event_status(session, market.event_id)
    dispute = (
        await session.execute(
            select(OracleDispute)
            .where(OracleDispute.market_id == market.id)
            .order_by(OracleDispute.created_at.desc())
        )
    ).scalars().first()
    if dispute is not None:
        dispute.status = "FINALIZED"
        dispute.proposed_outcome_index = effective_idx
        _append_audit_update(
            dispute,
            "FINALIZED",
            outcome_index=effective_idx,
            note="INVALID_50_50" if effective_idx == INVALID_OUTCOME_INDEX else None,
            extra={"resolved_invalid": effective_idx == INVALID_OUTCOME_INDEX},
        )
    return market


async def payout_for_token(market: Market, token: OutcomeToken) -> Decimal:
    """Settlement invariant: winning=1.00, losing=0.00, INVALID/CANCELLED (-1)=0.50 split."""
    if market.status != "RESOLVED" or market.winning_outcome_index is None:
        return Decimal(0)
    if market.winning_outcome_index == INVALID_OUTCOME_INDEX:
        n_outcomes = max(2, len(market.outcomes or []))
        return (Decimal("1.00") / Decimal(n_outcomes)).quantize(Decimal("0.01"))
    return (
        Decimal("1.00")
        if token.outcome_index == market.winning_outcome_index
        else Decimal("0.00")
    )


async def split_position(
    session: AsyncSession, user: User, market: Market, shares: Decimal
) -> list[Position]:
    """Atomic CTF split: 1.00 USDC -> 1 share of every outcome token.

    Locks collateral and mints one share of each outcome for the caller.
    """
    await ensure_market_open_for_trading(session, market)
    if shares <= 0:
        raise HTTPException(status_code=400, detail="Shares must be positive")

    tokens = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.market_id == market.id)
        )
    ).scalars().all()
    cost = to_dec(shares)
    account = await approval_account(session, user.id)
    available = to_dec(account.balance) - to_dec(account.locked_balance)
    if cost > available:
        raise HTTPException(status_code=400, detail="Insufficient available balance")
    # Collateral is consumed immediately and minted as outcome tokens (CTF).
    account.balance = to_dec(account.balance) - cost
    from app.services.collateral import _ledger

    await _ledger(session, account, "CTF_SPLIT", -cost, market.id)

    positions: list[Position] = []
    for token in tokens:
        position = await _get_position(session, user.id, token.token_id, for_update=True)
        if position is None:
            position = Position(
                user_id=user.id,
                market_id=market.id,
                token_id=token.token_id,
                shares=0,
                locked_shares=0,
            )
            session.add(position)
            await session.flush()
        position.shares = to_dec(position.shares) + shares
        position.avg_entry_price = Decimal("0.50")
        positions.append(position)
    return positions


async def merge_positions(
    session: AsyncSession, user: User, market: Market, shares: Decimal
) -> Decimal:
    """Atomic CTF merge: 1 share of every outcome -> 1.00 USDC collateral."""
    if market.status in ("UNFUNDED", "EXPIRED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot merge positions on {market.status} market",
        )
    if shares <= 0:
        raise HTTPException(status_code=400, detail="Shares must be positive")
    tokens = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.market_id == market.id)
        )
    ).scalars().all()
    for token in tokens:
        position = await _get_position(session, user.id, token.token_id, for_update=True)
        if position is None or to_dec(position.shares) - to_dec(
            position.locked_shares
        ) < shares:
            raise HTTPException(
                status_code=400, detail="Insufficient shares across full outcome set"
            )
    for token in tokens:
        position = await _get_position(session, user.id, token.token_id, for_update=True)
        position.shares = to_dec(position.shares) - shares
    account = await approval_account(session, user.id)
    cost = to_dec(shares)
    account.balance = to_dec(account.balance) + cost
    from app.services.collateral import _ledger

    await _ledger(session, account, "CTF_MERGE", cost, market.id)
    return cost


async def approval_account(session: AsyncSession, user_id: str):
    from app.services import collateral

    return await collateral.get_or_create_account(session, user_id, for_update=True)


async def _get_position(
    session: AsyncSession, user_id: str, token_id: str, *, for_update: bool = False
) -> Position | None:
    stmt = select(Position).where(
        Position.user_id == user_id, Position.token_id == token_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def redeem_position(
    session: AsyncSession, position: Position
) -> Decimal:
    if position.claimed:
        raise HTTPException(
            status_code=409, detail="Position has already been claimed"
        )
    if to_dec(position.shares) <= 0:
        raise HTTPException(status_code=409, detail="No shares held on this position")
    market = (
        await session.execute(select(Market).where(Market.id == position.market_id))
    ).scalar_one_or_none()
    if market is None or market.status != "RESOLVED":
        raise HTTPException(
            status_code=409, detail="Market is not RESOLVED; redemption unavailable"
        )
    token = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.token_id == position.token_id)
        )
    ).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=404, detail="Outcome token not found")
    payout = await payout_for_token(market, token) * to_dec(position.shares)
    position.claimed = True
    position.is_settled = True
    position.shares = 0
    return payout


def to_dec(value) -> Decimal:
    return Decimal(str(value))
