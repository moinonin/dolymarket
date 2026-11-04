"""Stage 1 verification: model instantiation and schema creation."""
import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.domain import (
    CollateralAccount,
    Event,
    Market,
    OracleDispute,
    Order,
    OutcomeToken,
    Position,
    TradeFill,
    User,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def session():
    return _SessionCtx()


class _SessionCtx:
    @property
    def ctx(self):
        return AsyncSessionLocal


async def test_models_import_and_tables_exist():
    from app.models.domain import Base

    tables = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "collateral_accounts",
        "events",
        "markets",
        "outcome_tokens",
        "orders",
        "trade_fills",
        "positions",
        "oracle_disputes",
    }
    assert expected.issubset(tables)


async def test_create_full_domain_graph():
    async with AsyncSessionLocal() as session:
        user = User(email="model-test@example.com", hashed_password="x" * 60)
        session.add(user)
        await session.flush()

        account = CollateralAccount(user_id=user.id, balance=1000, locked_balance=50)
        session.add(account)

        event = Event(slug="model-test-event", title="t", category="Crypto")
        session.add(event)
        await session.flush()

        market = Market(
            event_id=event.id,
            condition_id="0xc0nd1t10n",
            question="q",
            outcomes=["YES", "NO"],
        )
        session.add(market)
        await session.flush()

        token = OutcomeToken(
            token_id="tok-model", market_id=market.id, outcome_index=0, symbol="YES"
        )
        session.add(token)
        await session.flush()

        order = Order(
            user_id=user.id,
            market_id=market.id,
            token_id=token.token_id,
            side="BUY",
            type="LIMIT",
            price=0.50,
            amount=10,
        )
        session.add(order)
        await session.flush()

        fill = TradeFill(
            market_id=market.id,
            token_id=token.token_id,
            maker_order_id=order.id,
            taker_order_id=order.id,
            maker_user_id=user.id,
            taker_user_id=user.id,
            price=0.5,
            shares=10,
        )
        session.add(fill)

        position = Position(user_id=user.id, market_id=market.id, token_id=token.token_id, shares=10)
        session.add(position)

        dispute = OracleDispute(
            market_id=market.id,
            proposed_outcome_index=0,
            proposer_address="oracle",
            bond_amount=50,
            dispute_deadline=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        session.add(dispute)
        await session.flush()

        rows = (await session.execute(select(User).where(User.email == "model-test@example.com"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == user.id
