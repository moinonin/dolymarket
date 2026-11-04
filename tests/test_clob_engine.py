"""Stage 3 verification: CLOB engine unit tests (fee model, price-time, TIF)."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.engine.clob import (
    DEFAULT_FEE_RATE,
    MatchingEngine,
    OrderBook,
    compute_fee,
    fee_rate_for_category,
    validate_price,
)
from app.models.domain import (
    Event,
    Market,
    OutcomeToken,
    TradeFill,
    User,
)
from app.services import collateral


async def _make_market(session, category="Crypto", tick=0.01) -> tuple:
    user = User(email=f"maker-{category}-{tick}@e.com", hashed_password="x" * 60)
    session.add(user)
    await session.flush()
    await collateral.deposit(session, user, Decimal(100000))
    event = Event(slug=f"e-{category}-{tick}", title="t", category=category)
    session.add(event)
    await session.flush()
    market = Market(
        event_id=event.id,
        condition_id=f"cond-{user.id}",
        question="q",
        outcomes=["YES", "NO"],
        tick_size=tick,
        min_order_size=Decimal(5),
    )
    session.add(market)
    await session.flush()
    token = OutcomeToken(
        token_id=f"tok-{market.id}", market_id=market.id, outcome_index=0, symbol="YES"
    )
    session.add(token)
    await session.flush()
    return user, market, token


async def test_dynamic_fee_formula():
    fee_rate = Decimal("0.02")
    p = Decimal("0.60")
    c = Decimal(100)
    expected = c * fee_rate * p * (1 - p)
    assert compute_fee(c, fee_rate, p) == expected

    # Fee maximum at p=0.50
    assert compute_fee(Decimal(1), fee_rate, Decimal("0.50")) > compute_fee(
        Decimal(1), fee_rate, Decimal("0.10")
    )
    # symmetric at 0.10 / 0.90
    assert compute_fee(Decimal(1), fee_rate, Decimal("0.10")) == compute_fee(
        Decimal(1), fee_rate, Decimal("0.90")
    )
    assert fee_rate_for_category("Politics") == Decimal("0.015")
    assert fee_rate_for_category("Sports") == Decimal("0.025")
    assert fee_rate_for_category("Unknown") == DEFAULT_FEE_RATE


def test_price_bounds_and_tick():
    assert validate_price(Decimal("0.35"), Decimal("0.01")) is None
    with pytest.raises(ValueError):
        validate_price(Decimal("0.005"), Decimal("0.01"))
    with pytest.raises(ValueError):
        validate_price(Decimal("0.995"), Decimal("0.01"))
    with pytest.raises(ValueError):
        validate_price(Decimal("0.335"), Decimal("0.01"))


async def test_price_time_priority_fifo():
    async with AsyncSessionLocal() as session:
        user, market, token = await _make_market(session, category="Crypto")
        engine = MatchingEngine()
        # Two resting BUY orders at same price 0.30 -> FIFO.
        o1 = await engine.submit_order(
            session, user.id, market, token, collateral,
            side="BUY", price=Decimal("0.30"), amount=Decimal(10),
        )
        o2 = await engine.submit_order(
            session, user.id, market, token, collateral,
            side="BUY", price=Decimal("0.30"), amount=Decimal(10),
        )
        buys = await OrderBook(session, token.token_id).resting_orders("BUY")
        assert [b.id for b in buys][:2] == [o1.id, o2.id]
        await session.rollback()


async def test_ioc_partial_fill_and_fok_reject():
    async with AsyncSessionLocal() as session:
        seller = User(email="ioc-seller@e.com", hashed_password="x" * 60)
        session.add(seller)
        await session.flush()
        buyer = User(email="ioc-buyer@e.com", hashed_password="x" * 60)
        session.add(buyer)
        await session.flush()
        await collateral.deposit(session, seller, Decimal(10000))
        await collateral.deposit(session, buyer, Decimal(10000))
        from app.services.settlement import split_position
        
        event = Event(slug="ioc-event", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id, condition_id="cond-ioc", question="q",
            outcomes=["YES", "NO"], min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()
        token = OutcomeToken(
            token_id=f"tok-ioc-{market.id}", market_id=market.id, outcome_index=0, symbol="YES"
        )
        session.add(token)
        await session.flush()

        # Seller mints shares via CTF split and offers partial liquidity.
        await split_position(session, seller, market, Decimal(20))
        engine = MatchingEngine()
        await engine.submit_order(
            session, seller.id, market, token, collateral,
            side="SELL", price=Decimal("0.50"), amount=Decimal(10),
        )

        # IOC for 25 shares but only 10 resting -> fills 10, remainder cancelled.
        order = await engine.submit_order(
            session, buyer.id, market, token, collateral,
            side="BUY", price=Decimal("0.50"), amount=Decimal(25),
            time_in_force="IOC",
        )
        assert order.status == "CANCELLED"
        assert float(order.filled_amount) == 10.0
        fills = (
            await session.execute(select(TradeFill).where(TradeFill.taker_order_id == order.id))
        ).scalars().all()
        assert len(fills) == 1
        await session.rollback()


async def test_fok_rejects_entirely_without_liquidity():
    async with AsyncSessionLocal() as session:
        seller = User(email="fok-seller@e.com", hashed_password="x" * 60)
        session.add(seller)
        buyer = User(email="fok-buyer@e.com", hashed_password="x" * 60)
        session.add(buyer)
        await session.flush()
        await collateral.deposit(session, seller, Decimal(10000))
        await collateral.deposit(session, buyer, Decimal(10000))
        from app.services.settlement import split_position

        event = Event(slug="fok-event", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id, condition_id="cond-fok", question="q",
            outcomes=["YES", "NO"], min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()
        token = OutcomeToken(
            token_id=f"tok-fok-{market.id}", market_id=market.id, outcome_index=0, symbol="YES"
        )
        session.add(token)
        await session.flush()

        await split_position(session, seller, market, Decimal(20))
        engine = MatchingEngine()
        await engine.submit_order(
            session, seller.id, market, token, collateral,
            side="SELL", price=Decimal("0.50"), amount=Decimal(10),
        )

        # FOK for 25 shares but only 10 available -> 0 fills.
        order = await engine.submit_order(
            session, buyer.id, market, token, collateral,
            side="BUY", price=Decimal("0.50"), amount=Decimal(25),
            time_in_force="FOK",
        )
        assert order.status == "REJECTED"
        fills = (
            await session.execute(select(TradeFill).where(TradeFill.taker_order_id == order.id))
        ).scalars().all()
        assert len(fills) == 0
        await session.rollback()


async def test_ctf_split_and_merge_math():
    async with AsyncSessionLocal() as session:
        user = User(email="ctf@e.com", hashed_password="x" * 60)
        session.add(user)
        await session.flush()
        await collateral.deposit(session, user, Decimal(100))
        event = Event(slug="ctf-event", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id, condition_id="cond-ctf", question="q",
            outcomes=["YES", "NO"],
        )
        session.add(market)
        await session.flush()
        for idx, sym in enumerate(["YES", "NO"]):
            session.add(
                OutcomeToken(
                    token_id=f"tok-ctf-{idx}", market_id=market.id,
                    outcome_index=idx, symbol=sym,
                )
            )
        await session.flush()

        from app.services.settlement import merge_positions, split_position

        positions = await split_position(session, user, market, Decimal(10))
        assert len(positions) == 2
        balances = {p.token_id: Decimal(str(p.shares)) for p in positions}
        assert all(v == Decimal(10) for v in balances.values())
        account = await collateral.resolve_account(session, user.id)
        assert Decimal(str(account.balance)) == Decimal(90)

        returned = await merge_positions(session, user, market, Decimal(10))
        assert returned == Decimal(10)
        account = await collateral.resolve_account(session, user.id)
        assert Decimal(str(account.balance)) == Decimal(100)
        await session.rollback()


async def test_self_trade_prevention():
    async with AsyncSessionLocal() as session:
        user = User(email="stp@e.com", hashed_password="x" * 60)
        session.add(user)
        await session.flush()
        await collateral.deposit(session, user, Decimal(10000))
        from app.services.settlement import split_position

        event = Event(slug="stp-event", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id, condition_id="cond-stp", question="q",
            outcomes=["YES", "NO"], min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()
        token = OutcomeToken(
            token_id=f"tok-stp-{market.id}", market_id=market.id, outcome_index=0, symbol="YES"
        )
        session.add(token)
        await session.flush()

        await split_position(session, user, market, Decimal(30))
        engine = MatchingEngine()
        # Resting BUY from user at 0.55; user SELL @0.55 would self-match.
        await engine.submit_order(
            session, user.id, market, token, collateral,
            side="BUY", price=Decimal("0.55"), amount=Decimal(10),
        )
        resp = await engine.submit_order(
            session, user.id, market, token, collateral,
            side="SELL", price=Decimal("0.55"), amount=Decimal(10),
        )
        assert resp.status == "REJECTED"
        fills = (
            await session.execute(select(TradeFill).where(TradeFill.taker_order_id == resp.id))
        ).scalars().all()
        assert len(fills) == 0
        await session.rollback()
