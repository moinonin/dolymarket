"""Oracle resolution endpoints (UMA optimistic oracle pattern).

Resolution is a privileged operation: only admins/oracles may propose,
dispute or finalize, because finalize pays out every winning position.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_async_session
from app.models.domain import Event, Market, OracleDispute, User
from app.services import oracle, settlement

router = APIRouter(prefix="/api/v4/prediction/resolution", tags=["resolution"])


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("must be a finite number")
    return value


class ProposeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    proposed_outcome_index: int = Field(ge=0)
    evidence: dict | None = None


class DisputeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    counter_bond: Decimal = Field(default=Decimal("50"), gt=0, le=Decimal("100000"))
    evidence: dict | None = None

    @field_validator("counter_bond")
    @classmethod
    def _check_bond(cls, v: Decimal) -> Decimal:
        return _finite(v)


class FinalizeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    winning_outcome_index: int = Field(ge=0)


class FeedResolveRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    feed: str = Field(min_length=3, max_length=120)
    threshold: Decimal
    comparator: str = Field(default=">=", max_length=4)
    auto_finalize: bool = False

    @field_validator("threshold")
    @classmethod
    def _check_threshold(cls, v: Decimal) -> Decimal:
        return _finite(v)


@router.post("/propose")
async def propose(
    body: ProposeRequest,
    user: User = Depends(require_admin),
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
    if body.evidence is not None:
        dispute.evidence_json = body.evidence
    return {
        "market_id": market.id,
        "dispute_id": dispute.id,
        "proposed_outcome_index": dispute.proposed_outcome_index,
        "bond_amount": float(dispute.bond_amount),
        "dispute_deadline": dispute.dispute_deadline.isoformat(),
        "market_status": market.status,
        "evidence": dispute.evidence_json,
    }


@router.post("/dispute")
async def dispute(
    body: DisputeRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    result = await settlement.dispute_proposal(session, market, body.counter_bond)
    if body.evidence is not None:
        result.evidence_json = {**(result.evidence_json or {}), "dispute_evidence": body.evidence}
    return {
        "market_id": market.id,
        "dispute_id": result.id,
        "market_status": market.status,
        "evidence": result.evidence_json,
    }


@router.post("/finalize")
async def finalize(
    body: FinalizeRequest,
    user: User = Depends(require_admin),
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


@router.post("/resolve-feed")
async def resolve_with_deterministic_feed(
    body: FeedResolveRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Evaluate a deterministic price/event feed and propose (or finalize) resolution."""
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    proof = await oracle.evaluate_deterministic_feed(
        body.feed, body.threshold, comparator=body.comparator
    )
    win_idx = proof["winning_outcome_index"]
    dispute_row = await settlement.propose_resolution(session, market, win_idx)
    dispute_row.proposer_address = f"deterministic:{body.feed}"
    dispute_row.evidence_json = proof
    if body.auto_finalize:
        await settlement.finalize_resolution(session, market, win_idx)
    return {
        "market_id": market.id,
        "market_status": market.status,
        "winning_outcome_index": win_idx,
        "evidence": proof,
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
                "evidence": dispute.evidence_json if dispute else None,
            }
        )
    return {"markets": out}
