"""Oracle resolution endpoints (UMA optimistic oracle pattern).

Resolution is a privileged operation: only admins/oracles may propose,
dispute or finalize, because finalize pays out every winning position.
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_async_session
from app.models.domain import Event, Market, OracleDispute, User
from app.services import agx, oracle, settlement

logger = logging.getLogger("app.resolution")
router = APIRouter(prefix="/api/v4/prediction/resolution", tags=["resolution"])


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("must be a finite number")
    return value


class ProposeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    proposed_outcome_index: int = Field(ge=0)
    source_url: str | None = Field(default=None, max_length=2048)
    evidence_text: str | None = Field(default=None, max_length=8000)
    evidence: dict | None = None


class DisputeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    counter_bond: Decimal = Field(default=Decimal("100"), gt=0, le=Decimal("100000"))
    evidence: dict | None = None

    @field_validator("counter_bond")
    @classmethod
    def _check_bond(cls, v: Decimal) -> Decimal:
        return _finite(v)


class FinalizeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    winning_outcome_index: int = Field(default=0, ge=-1)
    resolve_invalid: bool = False


class ReproposeRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=64)
    reproposed_outcome_index: int = Field(ge=0)
    source_url: str | None = Field(default=None, max_length=2048)
    evidence_text: str | None = Field(default=None, max_length=8000)
    note: str | None = Field(default=None, max_length=500)


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
    src_url = body.source_url or (
        body.evidence.get("source_url") if isinstance(body.evidence, dict) else None
    )
    ev_text = body.evidence_text or (
        body.evidence.get("evidence_text") if isinstance(body.evidence, dict) else None
    )
    dispute = await settlement.propose_resolution(
        session,
        market,
        body.proposed_outcome_index,
        source_url=str(src_url) if src_url else None,
        evidence_text=str(ev_text) if ev_text else None,
    )
    base_ev = dict(dispute.evidence_json) if isinstance(dispute.evidence_json, dict) else {}
    if body.evidence is not None:
        dispute.evidence_json = {**base_ev, **body.evidence}
    elif src_url or ev_text:
        dispute.evidence_json = {
            **base_ev,
            **({"source_url": src_url} if src_url else {}),
            **({"evidence_text": ev_text} if ev_text else {}),
        }
    ev_meta = dispute.evidence_json if isinstance(dispute.evidence_json, dict) else {}
    return {
        "market_id": market.id,
        "dispute_id": dispute.id,
        "proposed_outcome_index": dispute.proposed_outcome_index,
        "bond_amount": float(dispute.bond_amount),
        "dispute_deadline": dispute.dispute_deadline.isoformat(),
        "market_status": market.status,
        "rules_hash": ev_meta.get("rules_hash"),
        "updates": ev_meta.get("updates", []),
        "evidence": dispute.evidence_json,
    }


@router.post("/repropose")
async def repropose(
    body: ReproposeRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Polymarket-style single re-proposal after a first dispute, opening a fresh 2h window."""
    market = (
        await session.execute(select(Market).where(Market.id == body.market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    prior_ev = None
    prior_dispute = (
        await session.execute(
            select(OracleDispute)
            .where(OracleDispute.market_id == market.id, OracleDispute.status == "DISPUTED")
            .order_by(OracleDispute.created_at.desc())
        )
    ).scalars().first()
    if prior_dispute and isinstance(prior_dispute.evidence_json, dict):
        prior_ev = dict(prior_dispute.evidence_json)

    dispute = await settlement.repropose_resolution(
        session,
        market,
        body.reproposed_outcome_index,
        actor=user.email or user.id,
        source_url=body.source_url,
        evidence_text=body.evidence_text,
        note=body.note,
    )
    if prior_ev:
        stake_id = prior_ev.get("agx_dispute_stake_id")
        orig_idx = prior_ev.get("original_proposed_index")
        if stake_id and orig_idx is not None:
            try:
                await agx.resolve_dispute(
                    session,
                    stake_id,
                    upheld=(body.reproposed_outcome_index != orig_idx),
                )
            except agx.AgxError as exc:
                logger.warning(
                    "AGX resolve_dispute skipped on repropose for market %s stake %s: %s",
                    market.id,
                    stake_id,
                    exc.code,
                )
    ev_meta = dispute.evidence_json if isinstance(dispute.evidence_json, dict) else {}
    return {
        "market_id": market.id,
        "dispute_id": dispute.id,
        "proposed_outcome_index": dispute.proposed_outcome_index,
        "reproposed_outcome_index": ev_meta.get("reproposed_outcome_index"),
        "dispute_deadline": dispute.dispute_deadline.isoformat(),
        "market_status": market.status,
        "rules_hash": ev_meta.get("rules_hash"),
        "updates": ev_meta.get("updates", []),
        "evidence": dispute.evidence_json,
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
    result = await settlement.dispute_proposal(session, market, body.counter_bond)
    try:
        stake = await agx.stake_dispute(session, user.id, market.id, body.counter_bond)
    except agx.AgxError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    orig_idx = result.proposed_outcome_index
    result.evidence_json = {
        **(result.evidence_json or {}),
        "agx_dispute_stake_id": stake.id,
        "disputer_user_id": user.id,
        "original_proposed_index": orig_idx,
        **({"dispute_evidence": body.evidence} if body.evidence is not None else {}),
    }
    return {
        "market_id": market.id,
        "dispute_id": result.id,
        "agx_dispute_stake_id": stake.id,
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
    prior_dispute = (
        await session.execute(
            select(OracleDispute)
            .where(OracleDispute.market_id == market.id)
            .order_by(OracleDispute.created_at.desc())
        )
    ).scalars().first()
    market = await settlement.finalize_resolution(
        session,
        market,
        body.winning_outcome_index,
        resolve_invalid=body.resolve_invalid,
    )
    if prior_dispute and isinstance(prior_dispute.evidence_json, dict):
        stake_id = prior_dispute.evidence_json.get("agx_dispute_stake_id")
        orig_idx = prior_dispute.evidence_json.get("original_proposed_index")
        if stake_id and orig_idx is not None:
            try:
                await agx.resolve_dispute(
                    session,
                    stake_id,
                    upheld=(market.winning_outcome_index != orig_idx),
                )
            except agx.AgxError as exc:
                logger.warning(
                    "AGX resolve_dispute skipped for market %s stake %s: %s",
                    market.id,
                    stake_id,
                    exc.code,
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
        "resolved_invalid": market.winning_outcome_index == settlement.INVALID_OUTCOME_INDEX,
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


@router.post("/run-tick")
async def trigger_resolution_tick(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Run one automated resolution lifecycle tick on demand."""
    from app.services.resolution_worker import run_resolution_tick
    from app.ws.manager import manager

    result = await run_resolution_tick(session)
    for event in result["broadcasts"]:
        await manager.broadcast(event)
    return {
        "closed": result["closed"],
        "expired": result["expired"],
        "proposed": result["proposed"],
        "finalized": result["finalized"],
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
        ev_meta = dispute.evidence_json if (dispute and isinstance(dispute.evidence_json, dict)) else {}
        out.append(
            {
                "market_id": m.id,
                "question": m.question,
                "event_title": event.title if event else None,
                "outcomes": m.outcomes,
                "market_status": m.status,
                "rules_hash": ev_meta.get("rules_hash") or settlement.compute_rules_hash(m, event),
                "dispute_status": dispute.status if dispute else None,
                "was_disputed": bool(ev_meta.get("was_disputed", False)),
                "proposed_outcome_index": (
                    dispute.proposed_outcome_index if dispute else None
                ),
                "reproposed_outcome_index": ev_meta.get("reproposed_outcome_index"),
                "proposer_address": dispute.proposer_address if dispute else None,
                "bond_amount": float(dispute.bond_amount) if dispute else None,
                "dispute_deadline": (
                    dispute.dispute_deadline.isoformat() if dispute else None
                ),
                "updates": ev_meta.get("updates", []),
                "evidence": dispute.evidence_json if dispute else None,
            }
        )
    return {"markets": out}
