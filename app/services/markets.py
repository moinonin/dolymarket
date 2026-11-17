"""Shared event & market creation helpers for Official (Admin) and Community markets."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Event, Market, OutcomeToken

PROHIBITED_CATEGORIES = frozenset({"assassination", "violence", "illegal", "terrorism"})
MIN_COMMUNITY_FUNDING_USDC = Decimal("10.0000")


def contains_prohibited_content(*texts: str | None) -> str | None:
    """Return matching prohibited keyword if any text violates content rules."""
    for raw in texts:
        if not raw:
            continue
        lower = raw.lower()
        for term in PROHIBITED_CATEGORIES:
            if term in lower:
                return term
    return None


def condition_id_from_seed(seed: str) -> str:
    return "0x" + hashlib.sha1(seed.encode()).hexdigest()


def parse_iso_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


async def create_event_record(
    session: AsyncSession,
    *,
    slug: str,
    title: str,
    description: str | None = None,
    category: str = "General",
    tags: list[str] | None = None,
    status: str = "ACTIVE",
    tier: str = "OFFICIAL",
    creator_user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Event:
    existing = (
        await session.execute(select(Event).where(Event.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("Event slug already exists")

    event = Event(
        slug=slug,
        title=title,
        description=description,
        category=category,
        tags=tags or [],
        status=status,
        tier=tier,
        creator_user_id=creator_user_id,
        start_date=parse_iso_dt(start_date),
        end_date=parse_iso_dt(end_date),
    )
    session.add(event)
    await session.flush()
    return event


async def create_market_record(
    session: AsyncSession,
    *,
    event: Event,
    question: str,
    outcomes: list[str],
    tick_size: float = 0.01,
    min_order_size: float = 5.0,
    status: str = "ACTIVE",
    tier: str = "OFFICIAL",
    creator_user_id: str | None = None,
    resolution_criteria: str | None = None,
    liquidity_funded_usdc: Decimal = Decimal("0"),
    neg_risk: bool = False,
) -> tuple[Market, list[OutcomeToken]]:
    cid = condition_id_from_seed(f"{event.slug}:{question}:{uuid.uuid4()}")
    market = Market(
        event_id=event.id,
        question=question,
        outcomes=outcomes,
        tick_size=max(0.0001, tick_size),
        min_order_size=max(0.0, min_order_size),
        status=status,
        tier=tier,
        creator_user_id=creator_user_id,
        resolution_criteria=resolution_criteria,
        liquidity_funded_usdc=liquidity_funded_usdc,
        neg_risk=neg_risk,
        condition_id=cid,
    )
    session.add(market)
    await session.flush()

    tokens: list[OutcomeToken] = []
    for idx, symbol in enumerate(outcomes):
        token = OutcomeToken(
            token_id=f"{market.condition_id}-{idx}",
            market_id=market.id,
            outcome_index=idx,
            symbol=symbol,
        )
        session.add(token)
        tokens.append(token)
    await session.flush()
    return market, tokens
