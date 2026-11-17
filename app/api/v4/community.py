"""Community Prediction Markets: permissionless market creation with safeguards & funding."""
from __future__ import annotations

import re
import uuid
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
    PROHIBITED_CATEGORIES,
    create_event_record,
    create_market_record,
)

router = APIRouter(prefix="/api/v4/prediction/community", tags=["community-markets"])


class CreateCommunityMarketRequest(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    question: str = Field(min_length=5, max_length=500)
    category: str = Field(default="Crypto", min_length=2, max_length=50)
    resolution_criteria: str = Field(min_length=10, max_length=2000)
    outcomes: list[str] = Field(default_factory=lambda: ["YES", "NO"], min_length=2, max_length=10)
    end_date: str | None = None
    initial_liquidity_usdc: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("100000"))
    oracle_feed: str | None = Field(default=None, max_length=120)
    bond_with_agx: bool = False

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
    if body.category.strip().lower() in PROHIBITED_CATEGORIES:
        raise HTTPException(status_code=400, detail="Prohibited market category")

    funded = body.initial_liquidity_usdc
    slug = _slugify(body.title)

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
    if body.oracle_feed:
        market.oracle_feed = body.oracle_feed.strip()
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
    await amm.deposit_liquidity(session, market, user.id, body.amount_usdc)

    return {
        "market_id": market.id,
        "status": market.status,
        "liquidity_funded_usdc": float(market.liquidity_funded_usdc),
        "min_required_usdc": float(MIN_COMMUNITY_FUNDING_USDC),
    }
