"""Demo seed data: creates an admin user, initial events, markets, tokens and
a small seeded order book so the UI shows a live CLOB from first launch.

Seeding is idempotent: it only runs when the events table is empty.
"""
import logging
from datetime import UTC, datetime
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

    try:
        await _seed_desks(session, trader, mm)
    except Exception as exc:  # pragma: no cover - seed best-effort
        logger.warning("Desk seed skipped: %s", exc)

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


async def _seed_desks(session, trader, mm) -> None:
    """Seed a couple of live Pro Desks with track records so the UI is populated."""
    from app.models.domain import Desk, DeskFollower, DeskPosition, Event, Market, OutcomeToken, Order, TradeFill

    # Macro desk owned by the demo trader.
    macro = Desk(owner_user_id=trader.id, name="Macro Desk", slug="macro-desk",
                 description="Macro event probabilities.", status="ACTIVE")
    macro.activated_at = datetime.now(UTC)
    session.add(macro)
    await session.flush()

    crypto = Desk(owner_user_id=mm.id, name="Crypto Desk", slug="crypto-desk",
                  description="Crypto market timing.", status="ACTIVE")
    crypto.activated_at = datetime.now(UTC)
    session.add(crypto)
    await session.flush()

    # A resolved market backing the macro desk's track record.
    event = Event(slug="seed-resolved-macro", title="Resolved Macro", category="Macro")
    session.add(event)
    await session.flush()
    market = Market(
        event_id=event.id, question="Resolved macro outcome?",
        outcomes=["YES", "NO"], tick_size=Decimal("0.01"), min_order_size=Decimal(5),
        status="RESOLVED", winning_outcome_index=0, condition_id="0xseedmacro",
    )
    session.add(market)
    await session.flush()
    tok = OutcomeToken(market_id=market.id, token_id=f"{market.condition_id}-0",
                       outcome_index=0, symbol="YES")
    session.add(tok)
    await session.flush()

    # Two settled positions (worked example): one win, one loss.
    session.add(DeskPosition(
        desk_id=macro.id, market_id=market.id, token_id=f"{market.condition_id}-0",
        outcome_index=0, shares=Decimal("100.0000"), avg_entry_price=Decimal("0.4000"),
        realized_pnl_usdc=Decimal("60.0000"), settled_at=datetime.now(UTC),
    ))
    session.add(DeskPosition(
        desk_id=macro.id, market_id=market.id, token_id=f"{market.condition_id}-1",
        outcome_index=1, shares=Decimal("50.0000"), avg_entry_price=Decimal("0.5500"),
        realized_pnl_usdc=Decimal("-27.5000"), settled_at=datetime.now(UTC),
    ))
    await session.flush()

    # A desk-tagged source fill carrying 0.50 of fees.
    order = Order(user_id=trader.id, market_id=market.id, token_id=f"{market.condition_id}-0",
                  side="BUY", type="LIMIT", price=Decimal("0.4000"), amount=Decimal("100"),
                  status="FILLED", desk_id=macro.id)
    session.add(order)
    await session.flush()
    fill = TradeFill(market_id=market.id, token_id=f"{market.condition_id}-0",
                     maker_order_id=order.id, taker_order_id=order.id,
                     maker_user_id=trader.id, taker_user_id=trader.id,
                     price=Decimal("0.4000"), shares=Decimal("100.0000"),
                     maker_fee=Decimal("0.5000"), taker_fee=Decimal("0.0000"))
    session.add(fill)
    await session.flush()

    # Crypto desk: a second ACTIVE desk with no track record yet.
    # Follower: trader follows mm's crypto desk.
    follower = DeskFollower(desk_id=crypto.id, follower_user_id=trader.id,
                           copy_ratio=Decimal("0.2500"), status="ACTIVE")
    session.add(follower)
    await session.flush()
