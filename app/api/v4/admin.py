"""Admin endpoints for creating events and markets (market admin / oracle)."""
import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import Event, Market, OutcomeToken, User

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


@router.post("/markets/{market_id}/close")
async def close_market(
    market_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Trading halt: ACTIVE -> CLOSED. Orders can no longer be placed."""
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
    return {"market_id": market.id, "status": market.status}


@router.post("/events", status_code=201)
async def create_event(
    body: CreateEventRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    existing = (
        await session.execute(select(Event).where(Event.slug == body.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Event slug already exists")

    def _parse(dt_str: str | None):
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    event = Event(
        slug=body.slug,
        title=body.title,
        description=body.description,
        category=body.category,
        tags=body.tags,
        status="ACTIVE",
        start_date=_parse(body.start_date) or datetime.now(UTC),
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
    event = (
        await session.execute(select(Event).where(Event.slug == body.event_slug))
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    market = Market(
        event_id=event.id,
        condition_id=_condition_id(f"{body.event_slug}:{body.question}:{uuid.uuid4()}"),
        question=body.question,
        outcomes=body.outcomes,
        tick_size=max(0.0001, body.tick_size),
        min_order_size=max(0.0, body.min_order_size),
        status="ACTIVE",
        neg_risk=body.neg_risk,
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
