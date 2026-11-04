"""Demo seed data: creates an admin user, initial events, markets, tokens and
a small seeded order book so the UI shows a live CLOB from first launch.

Seeding is idempotent: it only runs when the events table is empty.
"""
import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.engine.clob import MatchingEngine
from app.models.domain import Event, Market, OutcomeToken, User
from app.services import collateral, settlement

logger = logging.getLogger("seed")

DEMO_TRADER_EMAIL = "trader@demo.io"
DEMO_TRADER_PASSWORD = "trader-demo-1234"

EVENTS = [
    dict(
        slug="fed-interest-rate-decision",
        title="Fed Interest Rate Decision",
        description="Will the Federal Reserve cut rates at the next FOMC meeting?",
        category="Macro",
        tags=["fed", "rates", "macro"],
    ),
    dict(
        slug="us-presidential-election-2028",
        title="US Presidential Election 2028",
        description="Who will win the 2028 US presidential election?",
        category="Politics",
        tags=["election", "potus"],
    ),
    dict(
        slug="btc-150k-before-sept",
        title="BTC above $150K before September",
        description="Will Bitcoin close above $150,000 on any exchange before September 1?",
        category="Crypto",
        tags=["btc", "crypto"],
    ),
    dict(
        slug="nba-champion",
        title="NBA Champion",
        description="Which team will win the next NBA championship?",
        category="Sports",
        tags=["nba", "basketball"],
        neg_risk=True,
    ),
]


async def seed(session: AsyncSession) -> None:
    count = (
        await session.execute(select(func.count()).select_from(Event))
    ).scalar() or 0
    if count > 0:
        return

    # Demo trader with starting collateral.
    existing = (
        await session.execute(select(User).where(User.email == DEMO_TRADER_EMAIL))
    ).scalar_one_or_none()
    if existing is None:
        trader = User(
            email=DEMO_TRADER_EMAIL,
            hashed_password=security.hash_password(DEMO_TRADER_PASSWORD),
        )
        session.add(trader)
        await session.flush()
        await collateral.deposit(session, trader, Decimal(10000))

    mm_email = "market-maker@demo.io"
    mm = (
        await session.execute(select(User).where(User.email == mm_email))
    ).scalar_one_or_none()
    if mm is None:
        mm = User(
            email=mm_email,
            hashed_password=security.hash_password(DEMO_TRADER_PASSWORD),
        )
        session.add(mm)
        await session.flush()
        await collateral.deposit(session, mm, Decimal(50000))

    engine = MatchingEngine()

    trader = (
        await session.execute(select(User).where(User.email == DEMO_TRADER_EMAIL))
    ).scalar_one()

    for spec in EVENTS:
        event = Event(
            slug=spec["slug"],
            title=spec["title"],
            description=spec["description"],
            category=spec["category"],
            tags=spec.get("tags", []),
            status="ACTIVE",
        )
        session.add(event)
        await session.flush()

        question = spec["title"]
        if spec.get("neg_risk"):
            outcomes = ["Lakers", "Celtics", "Thunder", " Knicks"]
            question_root = "Which team wins the championship?"
        else:
            outcomes = ["YES", "NO"]
            question_root = f"Will {question}?"

        market = Market(
            event_id=event.id,
            condition_id=_fake_condition(spec["slug"]),
            question=question_root,
            outcomes=[o.strip() for o in outcomes],
            tick_size=Decimal("0.01"),
            min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()

        tokens = []
        for idx, symbol in enumerate([o.strip() for o in outcomes]):
            token = OutcomeToken(
                token_id=f"{market.condition_id}-{idx}",
                market_id=market.id,
                outcome_index=idx,
                symbol=symbol,
            )
            session.add(token)
            tokens.append(token)
        await session.flush()

        # Seed a two-sided book on the first outcome token.
        base = {"Macro": Decimal("0.35"), "Politics": Decimal("0.45"),
                "Crypto": Decimal("0.55"), "Sports": Decimal("0.25")}.get(
            spec["category"], Decimal("0.50")
        )
        try:
            await _seed_book(
                session, engine, trader, mm, market, tokens, base
            )
        except Exception as exc:  # pragma: no cover - seed best-effort
            logger.warning("Seed book skipped for %s: %s", spec["slug"], exc)

    await session.commit()


async def _seed_book(session, engine, trader, mm, market, tokens, base: Decimal) -> None:
    """Seed bid/ask liquidity around ``base``."""
    tick = Decimal("0.01")
    yes_token = tokens[0]

    # Market maker mints outcome shares via CTF split, then quotes asks.
    await settlement.split_position(session, mm, market, Decimal(250))
    asks = [base + tick * (i + 1) for i in range(3)]
    for p in asks:
        await engine.submit_order(
            session, mm.id, market, yes_token, collateral,
            side="SELL", price=p, amount=Decimal(50),
        )

    # Trader quotes bids below the ask ladder.
    for i in range(3):
        p = base - tick * (i + 1)
        await engine.submit_order(
            session, trader.id, market, yes_token, collateral,
            side="BUY", price=p, amount=Decimal(50),
        )


def _fake_condition(slug: str) -> str:
    import hashlib
    import uuid

    return "0x" + hashlib.sha1(f"{slug}:{uuid.uuid4()}".encode()).hexdigest()
