"""Oracle resolution endpoints (UMA optimistic oracle pattern)."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import Event, Market, OracleDispute, User
from app.services import settlement

router = APIRouter(prefix="/api/v4/prediction/resolution", tags=["resolution"])


class ProposeRequest(BaseModel):
    market_id: str
    proposed_outcome_index: int


class DisputeRequest(BaseModel):
    market_id: str
    counter_bond: float = 50.0


class FinalizeRequest(BaseModel):
    market_id: str
    winning_outcome_index: int


@router.post("/propose")
async def propose(
    body: ProposeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    dispute = await settlement.propose_resolution(
        session, market, body.proposed_outcome_index
    )
    return {
        "market_id": market.id,
        "dispute_id": dispute.id,
        "proposed_outcome_index": dispute.proposed_outcome_index,
        "bond_amount": float(dispute.bond_amount),
        "dispute_deadline": dispute.dispute_deadline.isoformat(),
        "market_status": market.status,
    }


@router.post("/dispute")
async def dispute(
    body: DisputeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    result = await settlement.dispute_proposal(
        session, market, Decimal(str(body.counter_bond))
    )
    return {
        "market_id": market.id,
        "dispute_id": result.id,
        "market_status": market.status,
    }


@router.post("/finalize")
async def finalize(
    body: FinalizeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    market = await settlement.finalize_resolution(
        session, market, body.winning_outcome_index
    )
    from app.ws.manager import manager

    await manager.broadcast(
        {
            "channel": "pred.status",
            "market_id": market.id,
            "status": market.status,
            "winning_outcome_index": market.winning_outcome_index,
        }
    )
    return {
        "market_id": market.id,
        "status": market.status,
        "winning_outcome_index": market.winning_outcome_index,
    }


@router.get("/markets")
async def resolution_markets(session: AsyncSession = Depends(get_async_session)):
    """Public view of all markets in IN_RESOLUTION or DISPUTED status."""
    markets = (
        await session.execute(
            select(Market).where(Market.status.in_(("IN_RESOLUTION", "DISPUTED")))
        )
    ).scalars().all()
    out = []
    for m in markets:
        dispute = (
            await session.execute(
                select(OracleDispute)
                .where(OracleDispute.market_id == m.id)
                .order_by(OracleDispute.created_at.desc())
            )
        ).scalars().first()
        event = (
            await session.execute(select(Event).where(Event.id == m.event_id))
        ).scalar_one_or_none()
        out.append(
            {
                "market_id": m.id,
                "question": m.question,
                "event_title": event.title if event else None,
                "outcomes": m.outcomes,
                "market_status": m.status,
                "dispute_status": dispute.status if dispute else None,
                "proposed_outcome_index": (
                    dispute.proposed_outcome_index if dispute else None
                ),
                "proposer_address": dispute.proposer_address if dispute else None,
                "bond_amount": float(dispute.bond_amount) if dispute else None,
                "dispute_deadline": (
                    dispute.dispute_deadline.isoformat() if dispute else None
                ),
            }
        )
    return {"markets": out}
