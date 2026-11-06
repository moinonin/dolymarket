"""Admin endpoints for creating events and markets (market admin / oracle).

Every route in this namespace is admin-only: creating an event, creating a
market, closing a market, reviewing Pro Desks and inspecting copy-job history
all answer HTTP 403 ``ADMIN_REQUIRED`` for a regular account.
"""
import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import CopyJob, Desk, DeskFollower, Event, Market, OutcomeToken, User

router = APIRouter(prefix="/api/v4/prediction/admin", tags=["admin"])


class CreateEventRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str = "Politics"
    tags: list[str] = []
    start_date: str | None = None
    end_date: str | None = None


class CreateMarketRequest(BaseModel):
    event_slug: str
    question: str = Field(min_length=1, max_length=500)
    outcomes: list[str] = Field(min_length=2, max_length=10)
    tick_size: float = 0.01
    min_order_size: float = 5.0
    neg_risk: bool = False


def _condition_id(market_seed: str) -> str:
    return "0x" + hashlib.sha1(market_seed.encode()).hexdigest()


async def _require_admin(user: User) -> User:
    """Every admin route is admin-only."""
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="ADMIN_REQUIRED")
    return user


@router.post("/markets/{market_id}/close")
async def close_market(
    market_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Trading halt: ACTIVE -> CLOSED. Orders can no longer be placed."""
    await _require_admin(user)
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status not in ("ACTIVE", "SUSPENDED"):
        raise HTTPException(
            status_code=409,
            detail=f"Market cannot be closed from status {market.status}",
        )
    market.status = "CLOSED"
    event = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()
    if event is not None:
        event.status = "CLOSED"
    await session.flush()
    return {"market_id": market.id, "status": market.status}


@router.post("/events", status_code=201)
async def create_event(
    body: CreateEventRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    await _require_admin(user)
    existing = (
        await session.execute(select(Event).where(Event.slug == body.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Event slug already exists")

    def _parse(dt_str: str | None):
        if not dt_str:
            return None
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

    event = Event(
        slug=body.slug,
        title=body.title,
        description=body.description,
        category=body.category,
        tags=body.tags,
        start_date=_parse(body.start_date),
        end_date=_parse(body.end_date),
    )
    session.add(event)
    await session.flush()
    return {
        "id": event.id,
        "slug": event.slug,
        "title": event.title,
        "category": event.category,
        "status": event.status,
    }


@router.post("/markets", status_code=201)
async def create_market(
    body: CreateMarketRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    await _require_admin(user)
    event = (
        await session.execute(select(Event).where(Event.slug == body.event_slug))
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    market = Market(
        event_id=event.id,
        question=body.question,
        outcomes=body.outcomes,
        tick_size=max(0.0001, body.tick_size),
        min_order_size=max(0.0, body.min_order_size),
        status="ACTIVE",
        neg_risk=body.neg_risk,
        condition_id=_condition_id(f"{body.event_slug}:{body.question}:{uuid.uuid4()}"),
    )
    session.add(market)
    await session.flush()

    tokens = []
    for idx, symbol in enumerate(body.outcomes):
        token = OutcomeToken(
            token_id=f"{market.condition_id}-{idx}",
            market_id=market.id,
            outcome_index=idx,
            symbol=symbol,
        )
        session.add(token)
        tokens.append(token)
    await session.flush()

    return {
        "id": market.id,
        "event_id": market.event_id,
        "condition_id": market.condition_id,
        "question": market.question,
        "outcomes": market.outcomes,
        "status": market.status,
        "tokens": [
            {"token_id": t.token_id, "outcome_index": t.outcome_index, "symbol": t.symbol}
            for t in tokens
        ],
    }


class RejectDeskRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/desks/{desk_id}/approve")
async def approve_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    await _require_admin(user)
    desk = (await session.execute(select(Desk).where(Desk.id == desk_id))).scalar_one_or_none()
    if desk is None:
        raise HTTPException(status_code=404, detail="Desk not found")
    if desk.status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    desk.status = "ACTIVE"
    desk.activated_at = datetime.now(UTC)
    desk.review_note = None
    await session.flush()
    return {"status": "ACTIVE", "desk_id": desk.id}


@router.post("/desks/{desk_id}/reject")
async def reject_desk(
    desk_id: str,
    body: RejectDeskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    await _require_admin(user)
    desk = (await session.execute(select(Desk).where(Desk.id == desk_id))).scalar_one_or_none()
    if desk is None:
        raise HTTPException(status_code=404, detail="Desk not found")
    if desk.status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    desk.status = "REJECTED"
    desk.review_note = body.reason
    await session.flush()
    return {"status": "REJECTED", "desk_id": desk.id}


@router.post("/desks/{desk_id}/suspend")
async def admin_suspend_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    await _require_admin(user)
    desk = (await session.execute(select(Desk).where(Desk.id == desk_id))).scalar_one_or_none()
    if desk is None:
        raise HTTPException(status_code=404, detail="Desk not found")
    if desk.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    desk.status = "SUSPENDED"
    desk.suspended_at = datetime.now(UTC)
    await session.flush()
    return {"status": "SUSPENDED", "desk_id": desk.id}


@router.get("/desks")
async def list_desks_for_review(
    status: str = Query(default="PENDING_REVIEW"),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Desk review queue (admin only).

    Defaults to the desks waiting for review; pass ``status=`` to list another
    lifecycle state (for example ``ACTIVE`` or ``SUSPENDED``).
    """
    await _require_admin(user)
    stmt = select(Desk)
    if status:
        stmt = stmt.where(Desk.status == status)
    desks = (await session.execute(stmt.order_by(Desk.created_at.desc()).limit(limit))).scalars().all()

    out = []
    for desk in desks:
        owner = (
            await session.execute(select(User).where(User.id == desk.owner_user_id))
        ).scalar_one_or_none()
        follower_count = (
            await session.execute(
                select(DeskFollower).where(DeskFollower.desk_id == desk.id)
            )
        ).scalars().all()
        out.append(
            {
                "id": desk.id,
                "name": desk.name,
                "slug": desk.slug,
                "description": desk.description,
                "status": desk.status,
                "review_note": desk.review_note,
                "owner_email": owner.email if owner else None,
                "follower_count": len(follower_count),
                "created_at": str(desk.created_at),
                "activated_at": str(desk.activated_at) if desk.activated_at else None,
                "suspended_at": str(desk.suspended_at) if desk.suspended_at else None,
            }
        )
    return {"desks": out, "status": status or None}


@router.get("/copy-jobs")
async def list_copy_jobs_admin(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Copy-job history across every account (admin only)."""
    await _require_admin(user)
    stmt = select(CopyJob)
    if status:
        stmt = stmt.where(CopyJob.status == status)
    jobs = (
        await session.execute(stmt.order_by(CopyJob.created_at.desc()).limit(limit))
    ).scalars().all()

    desk_names: dict[str, str] = {}
    follower_emails: dict[str, str] = {}
    for job in jobs:
        if job.desk_id not in desk_names:
            desk = (
                await session.execute(select(Desk).where(Desk.id == job.desk_id))
            ).scalar_one_or_none()
            desk_names[job.desk_id] = desk.name if desk else job.desk_id
        if job.follower_user_id not in follower_emails:
            follower = (
                await session.execute(select(User).where(User.id == job.follower_user_id))
            ).scalar_one_or_none()
            follower_emails[job.follower_user_id] = follower.email if follower else job.follower_user_id

    return {
        "jobs": [
            {
                "id": j.id,
                "desk_id": j.desk_id,
                "desk_name": desk_names.get(j.desk_id),
                "follower_email": follower_emails.get(j.follower_user_id),
                "source_fill_id": j.source_fill_id,
                "status": j.status,
                "copy_ratio": float(j.copy_ratio),
                "requested_shares": float(j.requested_shares),
                "filled_shares": float(j.filled_shares),
                "limit_breached": j.limit_breached,
                "error_code": j.error_code,
                "created_at": str(j.created_at),
            }
            for j in jobs
        ],
        "status": status or None,
    }