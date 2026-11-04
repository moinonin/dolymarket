"""Conditional Tokens Framework (CTF) settlement and oracle resolution.

Implements the UMA optimistic oracle pattern: bonded proposal, dispute
counter-bond with a simulated challenge window, and atomic 1:1 payout of
winning outcome tokens ($1.00 USDC per share; losing shares pay $0.00).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Event, Market, OracleDispute, OutcomeToken, Position, User

DISPUTE_WINDOW = timedelta(hours=2)
PROPOSAL_BOND = Decimal(50)


def _now() -> datetime:
    return datetime.now(UTC)


async def propose_resolution(
    session: AsyncSession, market: Market, proposed_outcome_index: int
) -> OracleDispute:
    if market.status not in ("CLOSED",):
        raise HTTPException(
            status_code=409,
            detail=f"Market must be CLOSED to propose resolution (current: {market.status})",
        )
    if proposed_outcome_index < 0 or proposed_outcome_index >= len(market.outcomes or []):
        raise HTTPException(status_code=422, detail="Invalid proposed outcome index")
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

    dispute = OracleDispute(
        market_id=market.id,
        proposed_outcome_index=proposed_outcome_index,
        proposer_address="uma-optimistic-oracle",
        bond_amount=PROPOSAL_BOND,
        dispute_deadline=_now() + DISPUTE_WINDOW,
        status="PROPOSED",
    )
    session.add(dispute)
    market.status = "IN_RESOLUTION"
    event = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    if event is not None and event.status == "ACTIVE":
        event.status = "CLOSED"
    return dispute


async def dispute_proposal(
    session: AsyncSession, market: Market, counter_bond: Decimal
) -> OracleDispute:
    dispute = (
        await session.execute(
            select(OracleDispute).where(
                OracleDispute.market_id == market.id,
                OracleDispute.status.in_(("PROPOSED",)),
            )
        )
    ).scalar_one_or_none()
    if dispute is None:
        raise HTTPException(status_code=404, detail="No pending resolution proposal")
    if market.status != "IN_RESOLUTION":
        raise HTTPException(status_code=409, detail="Market is not IN_RESOLUTION")
    if _now() > dispute.dispute_deadline:
        raise HTTPException(status_code=409, detail="Dispute window has expired")
    if counter_bond < dispute.bond_amount:
        raise HTTPException(status_code=400, detail="Counter-bond below proposal bond")
    dispute.status = "DISPUTED"
    market.status = "DISPUTED"
    return dispute


async def finalize_resolution(
    session: AsyncSession, market: Market, winning_outcome_index: int
) -> Market:
    if market.status not in ("IN_RESOLUTION", "DISPUTED", "CLOSED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resolve market in status {market.status}",
        )
    if winning_outcome_index < 0 or winning_outcome_index >= len(market.outcomes or []):
        raise HTTPException(status_code=422, detail="Invalid winning outcome index")
    market.winning_outcome_index = winning_outcome_index
    market.status = "RESOLVED"
    event = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    if event is not None:
        event.status = "RESOLVED"
    dispute = (
        await session.execute(
            select(OracleDispute)
            .where(OracleDispute.market_id == market.id)
            .order_by(OracleDispute.created_at.desc())
        )
    ).scalars().first()
    if dispute is not None:
        dispute.status = "FINALIZED"
        dispute.proposed_outcome_index = winning_outcome_index
    return market


async def payout_for_token(market: Market, token: OutcomeToken) -> Decimal:
    """Settlement invariant: winning token == 1.00, losing token == 0.00."""
    if market.status != "RESOLVED" or market.winning_outcome_index is None:
        return Decimal(0)
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
    if market.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Market is not ACTIVE for splitting")
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
        position = await _get_position(session, user.id, token.token_id)
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
    if shares <= 0:
        raise HTTPException(status_code=400, detail="Shares must be positive")
    tokens = (
        await session.execute(
            select(OutcomeToken).where(OutcomeToken.market_id == market.id)
        )
    ).scalars().all()
    for token in tokens:
        position = await _get_position(session, user.id, token.token_id)
        if position is None or to_dec(position.shares) - to_dec(
            position.locked_shares
        ) < shares:
            raise HTTPException(
                status_code=400, detail="Insufficient shares across full outcome set"
            )
    for token in tokens:
        position = await _get_position(session, user.id, token.token_id)
        position.shares = to_dec(position.shares) - shares
    account = await approval_account(session, user.id)
    cost = to_dec(shares)
    account.balance = to_dec(account.balance) + cost
    from app.services.collateral import _ledger

    await _ledger(session, account, "CTF_MERGE", cost, market.id)
    return cost


def approval_account(session: AsyncSession, user_id: str):
    from app.models.domain import CollateralAccount

    return session.scalar(
        select(CollateralAccount).where(CollateralAccount.user_id == user_id)
    )


async def _get_position(
    session: AsyncSession, user_id: str, token_id: str
) -> Position | None:
    return (
        await session.execute(
            select(Position).where(
                Position.user_id == user_id, Position.token_id == token_id
            )
        )
    ).scalar_one_or_none()


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
