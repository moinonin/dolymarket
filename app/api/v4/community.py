"""Community Prediction Markets: permissionless market creation with safeguards & funding."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import Event, Market, User
from app.services import amm
from app.services.markets import (
    MIN_COMMUNITY_FUNDING_USDC,
    contains_prohibited_content,
    create_event_record,
    create_market_record,
    parse_iso_dt,
)

router = APIRouter(prefix="/api/v4/prediction/community", tags=["community-markets"])


class ClarityPreviewRequest(BaseModel):
    question: str = Field(default="", max_length=500)
    resolution_criteria: str = Field(default="", max_length=2000)
    end_date: str | None = None
    oracle_feed: str | None = Field(default=None, max_length=120)


@router.post("/clarity-preview")
async def preview_community_clarity(body: ClarityPreviewRequest):
    """Live <1ms Oracle Clarity & Category preview for community market creation."""
    from app.services import oracle

    return oracle.compute_clarity_score(
        body.resolution_criteria,
        question=body.question,
        end_date=body.end_date or None,
        oracle_feed=body.oracle_feed or None,
    )


class CreateCommunityMarketRequest(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    question: str = Field(min_length=5, max_length=500)
    category: str = Field(default="Crypto", min_length=2, max_length=50)
    resolution_criteria: str = Field(min_length=10, max_length=2000)
    outcomes: list[str] = Field(default_factory=lambda: ["YES", "NO"], min_length=2, max_length=2)
    end_date: str = Field(..., min_length=4)
    initial_liquidity_usdc: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("100000"))
    oracle_feed: str | None = Field(default=None, max_length=120)
    oracle_threshold: Decimal | None = Field(default=None)
    oracle_comparator: str | None = Field(default=None, max_length=4)
    bond_with_agx: bool = False

    @field_validator("end_date")
    @classmethod
    def _valid_future_end_date(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("end_date is required")
        try:
            dt = parse_iso_dt(v.strip())
        except ValueError as exc:
            raise ValueError("Invalid ISO-8601 end_date") from exc
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt <= datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("end_date must be at least 5 minutes in the future")
        return dt.isoformat()

    @field_validator("outcomes")
    @classmethod
    def _valid_binary_outcomes(cls, v: list[str]) -> list[str]:
        cleaned = [o.strip() for o in v if o and o.strip()]
        if len(cleaned) != 2:
            raise ValueError("Community markets require exactly 2 outcomes")
        return cleaned

    @field_validator("oracle_threshold")
    @classmethod
    def _finite_threshold(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("must be finite")
        return v

    @field_validator("oracle_comparator")
    @classmethod
    def _valid_comparator(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        cleaned = v.strip()
        if cleaned not in (">=", ">", "<=", "<"):
            raise ValueError("comparator must be one of >=, >, <=, <")
        return cleaned

    @field_validator("initial_liquidity_usdc")
    @classmethod
    def _finite_amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be finite")
        return v


class FundCommunityMarketRequest(BaseModel):
    amount_usdc: Decimal = Field(gt=Decimal("0"), le=Decimal("100000"))

    @field_validator("amount_usdc")
    @classmethod
    def _finite_amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be finite")
        return v


def _slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "market"
    return f"community-{base}-{uuid.uuid4().hex[:6]}"


@router.post("/markets", status_code=201)
async def create_community_market(
    body: CreateCommunityMarketRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    if contains_prohibited_content(
        body.category, body.title, body.question, body.resolution_criteria
    ):
        raise HTTPException(status_code=400, detail="Prohibited market category or content")

    from app.services import oracle

    validated_feed: str | None = None
    if body.oracle_feed and body.oracle_feed.strip():
        validated_feed = oracle.validate_oracle_feed(body.oracle_feed, allow_static=False)
        if body.oracle_threshold is None:
            raise HTTPException(
                status_code=422,
                detail="oracle_threshold is required when oracle_feed is specified",
            )
    elif body.oracle_threshold is not None:
        raise HTTPException(
            status_code=422,
            detail="oracle_feed is required when oracle_threshold is specified",
        )

    funded = body.initial_liquidity_usdc
    slug = _slugify(body.title)

    try:
        event = await create_event_record(
            session,
            slug=slug,
            title=body.title.strip(),
            description=body.resolution_criteria.strip(),
            category=body.category.strip(),
            tags=["Community"],
            status="UNFUNDED",
            tier="COMMUNITY",
            creator_user_id=user.id,
            end_date=body.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    market, tokens = await create_market_record(
        session,
        event=event,
        question=body.question.strip(),
        outcomes=body.outcomes,
        status="UNFUNDED",
        tier="COMMUNITY",
        creator_user_id=user.id,
        resolution_criteria=body.resolution_criteria.strip(),
        liquidity_funded_usdc=Decimal("0"),
    )
    if validated_feed:
        market.oracle_feed = validated_feed
    if body.oracle_threshold is not None:
        market.oracle_threshold = body.oracle_threshold
        market.oracle_comparator = body.oracle_comparator or ">="
    if body.bond_with_agx:
        from app.services import agx

        await agx.ensure_market_bond(session, user.id, market.id)
    if funded > 0:
        await amm.deposit_liquidity(session, market, user.id, funded)
    from app.services import oracle

    return {
        "event_id": event.id,
        "slug": event.slug,
        "market_id": market.id,
        "condition_id": market.condition_id,
        "tier": market.tier,
        "status": market.status,
        "oracle_feed": market.oracle_feed,
        "oracle_threshold": float(market.oracle_threshold) if market.oracle_threshold is not None else None,
        "oracle_comparator": market.oracle_comparator,
        "clarity": oracle.compute_clarity_score(
            market.resolution_criteria,
            question=market.question,
            end_date=body.end_date,
            oracle_feed=market.oracle_feed,
        ),
        "liquidity_funded_usdc": float(market.liquidity_funded_usdc),
        "tokens": [{"token_id": t.token_id, "symbol": t.symbol} for t in tokens],
    }


@router.post("/markets/{market_id}/fund")
async def fund_community_market(
    market_id: str,
    body: FundCommunityMarketRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    if getattr(market, "tier", "OFFICIAL") != "COMMUNITY":
        raise HTTPException(
            status_code=403, detail="Only COMMUNITY markets can be funded via community endpoint"
        )
    await amm.deposit_liquidity(session, market, user.id, body.amount_usdc)

    return {
        "market_id": market.id,
        "status": market.status,
        "liquidity_funded_usdc": float(market.liquidity_funded_usdc),
        "min_required_usdc": float(MIN_COMMUNITY_FUNDING_USDC),
    }


class UpdateCommunityMarketRequest(BaseModel):
    title: str | None = Field(default=None, min_length=5, max_length=200)
    question: str | None = Field(default=None, min_length=5, max_length=500)
    category: str | None = Field(default=None, min_length=2, max_length=50)
    resolution_criteria: str | None = Field(default=None, min_length=10, max_length=2000)
    end_date: str | None = None
    oracle_feed: str | None = Field(default=None, max_length=120)
    oracle_threshold: Decimal | None = Field(default=None)
    oracle_comparator: str | None = Field(default=None, max_length=4)

    @field_validator("end_date")
    @classmethod
    def _valid_future_end_date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.strip():
            raise ValueError("end_date cannot be empty")
        try:
            dt = parse_iso_dt(v.strip())
        except ValueError as exc:
            raise ValueError("Invalid ISO-8601 end_date") from exc
        if dt is None:
            raise ValueError("Invalid ISO-8601 end_date")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt <= datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("end_date must be at least 5 minutes in the future")
        return dt.isoformat()


@router.patch("/markets/{market_id}")
async def update_community_market(
    market_id: str,
    body: UpdateCommunityMarketRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Edit an UNFUNDED community market created by the caller. Locked once ACTIVE."""
    from sqlalchemy import func
    from app.models.domain import Order
    from app.services import oracle

    market = (
        await session.execute(select(Market).where(Market.id == market_id))
    ).scalar_one_or_none()
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")
    if getattr(market, "tier", "OFFICIAL") != "COMMUNITY":
        raise HTTPException(status_code=403, detail="Only COMMUNITY markets can be edited here")
    if getattr(market, "creator_user_id", None) != user.id:
        raise HTTPException(status_code=403, detail="Only the market creator can edit this market")
    if market.status != "UNFUNDED":
        raise HTTPException(
            status_code=409,
            detail=f"Market is locked (status={market.status}); only UNFUNDED markets can be edited",
        )
    if Decimal(str(getattr(market, "liquidity_funded_usdc", 0) or 0)) > 0:
        raise HTTPException(
            status_code=409,
            detail="Market already has LP deposits and cannot be edited",
        )

    order_count = (
        await session.execute(select(func.count()).select_from(Order).where(Order.market_id == market.id))
    ).scalar() or 0
    if order_count > 0:
        raise HTTPException(status_code=409, detail="Market already has orders and cannot be edited")

    event = (
        await session.execute(select(Event).where(Event.id == market.event_id))
    ).scalar_one_or_none()

    # Safeguard check on any updated text fields
    combined_check = " ".join(
        filter(None, [body.title, body.question, body.category, body.resolution_criteria])
    )
    if combined_check and contains_prohibited_content(combined_check):
        raise HTTPException(status_code=400, detail="Prohibited content in market update")

    if body.title is not None and event is not None:
        event.title = body.title.strip()
    if body.category is not None and event is not None:
        event.category = body.category.strip()
    if body.end_date is not None and event is not None:
        event.end_date = parse_iso_dt(body.end_date)
    if body.question is not None:
        market.question = body.question.strip()
    if body.resolution_criteria is not None:
        crit = body.resolution_criteria.strip()
        market.resolution_criteria = crit
        if event is not None:
            event.description = crit
    if body.oracle_feed is not None:
        feed = body.oracle_feed.strip()
        if feed:
            market.oracle_feed = oracle.validate_oracle_feed(feed, allow_static=False)
        else:
            market.oracle_feed = None
    if body.oracle_threshold is not None:
        market.oracle_threshold = body.oracle_threshold
    if body.oracle_comparator is not None:
        market.oracle_comparator = body.oracle_comparator

    await session.flush()
    end_dt = event.end_date if event is not None else None
    return {
        "market_id": market.id,
        "status": market.status,
        "title": event.title if event is not None else None,
        "question": market.question,
        "resolution_criteria": market.resolution_criteria,
        "category": event.category if event is not None else None,
        "end_date": str(end_dt) if end_dt is not None else None,
        "clarity": oracle.compute_clarity_score(
            market.resolution_criteria,
            question=market.question,
            end_date=end_dt,
            oracle_feed=market.oracle_feed,
            outcomes=market.outcomes,
        ),
    }
