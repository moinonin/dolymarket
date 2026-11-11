"""AGX feature gating (Pro Desk, official markets) and CLOB taker discounts."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.engine.clob import MatchingEngine
from app.models.domain import Event, Market, OutcomeToken, TradeFill, User
from app.services import agx, collateral
from app.services.settlement import split_position
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def agx_user(client: AsyncClient, email: str, funded: str = "10000"):
    headers = await auth_headers(client, email)
    await make_admin(email)
    resp = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": funded},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return headers


async def user_id(email: str) -> str:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one()


async def seed_market(slug: str) -> str:
    async with AsyncSessionLocal() as session:
        event = Event(slug=slug, title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id,
            condition_id=f"cond-{slug}",
            question="q",
            outcomes=["YES", "NO"],
        )
        session.add(market)
        await session.flush()
        await session.commit()
        return market.id


async def test_pro_desk_requires_500_agx(client: AsyncClient):
    headers = await agx_user(client, "gate-desk-low@example.com", funded="499.999")

    resp = await client.post(
        "/api/v1/desks",
        json={"name": "Pro", "slug": "pro-low", "pro": True},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "AGX_INSUFFICIENT_GATE"

    mine = await client.get("/api/v1/desks/mine", headers=headers)
    assert mine.status_code == 404

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["locked_gating_balance"] == "0.000000000000000000"


async def test_pro_desk_bond_locks_and_refunds_on_archive(client: AsyncClient):
    headers = await agx_user(client, "gate-desk-ok@example.com", funded="500")

    created = await client.post(
        "/api/v1/desks",
        json={"name": "Pro", "slug": "pro-ok", "pro": True},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["locked_gating_balance"] == "500.000000000000000000"
    assert balance["balance"] == "0.000000000000000000"

    desk_id = created.json()["desk"]["id"]
    archived = await client.post(f"/api/v1/desks/{desk_id}/archive", headers=headers)
    assert archived.status_code == 200, archived.text

    refunded = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert refunded["locked_gating_balance"] == "0.000000000000000000"
    assert refunded["balance"] == "500.000000000000000000"


async def test_standard_desk_stays_zero_token(client: AsyncClient):
    headers = await auth_headers(client, "gate-community@example.com")
    resp = await client.post(
        "/api/v1/desks",
        json={"name": "Community", "slug": "community-zero"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["balance"] == "0.000000000000000000"
    assert balance["locked_gating_balance"] == "0.000000000000000000"
    assert balance["tier"] == "0"


async def test_official_market_gate_thresholds(client: AsyncClient):
    email = "gate-market@example.com"
    await agx_user(client, email, funded="999.999")
    uid = await user_id(email)
    market_id = await seed_market("gate-market")

    # Deployment is a fixed 1,000 AGX bond: 999.999 spendable is not enough.
    async with AsyncSessionLocal() as session:
        with pytest.raises(agx.AgxError) as rejected:
            await agx.lock_market_gating(session, uid, market_id)
        assert rejected.value.code == "AGX_INSUFFICIENT_GATE"
        assert rejected.value.status_code == 409
        await session.rollback()

    # Topping up to exactly 1,000 AGX makes the same deployment succeed.
    await agx_user(client, email, funded="1000")
    async with AsyncSessionLocal() as session:
        record = await agx.lock_market_gating(session, uid, market_id)
        await session.commit()
        assert record.amount == Decimal("1000")
        assert record.status == "LOCKED"

        row = await agx.peek_balance(session, uid)
        assert Decimal(row.locked_gating_balance) == Decimal("1000")
        assert Decimal(row.balance) == Decimal("0")

    async with AsyncSessionLocal() as session:
        released = await agx.release_market_gating(session, uid, market_id)
        await session.commit()
        assert released.status == "RELEASED"

        row = await agx.peek_balance(session, uid)
        assert Decimal(row.locked_gating_balance) == Decimal("0")
        assert Decimal(row.balance) == Decimal("1000")

    async with AsyncSessionLocal() as session:
        record = await agx.lock_market_gating(session, uid, market_id, "1000")
        await session.commit()
        assert record.amount == Decimal("1000")
        assert record.status == "LOCKED"

        row = await agx.peek_balance(session, uid)
        assert Decimal(row.locked_gating_balance) == Decimal("1000")
        assert Decimal(row.balance) == Decimal("0")

    async with AsyncSessionLocal() as session:
        released = await agx.release_market_gating(session, uid, market_id)
        await session.commit()
        assert released.status == "RELEASED"

        row = await agx.peek_balance(session, uid)
        assert Decimal(row.locked_gating_balance) == Decimal("0")
        assert Decimal(row.balance) == Decimal("1000")


async def test_clob_taker_discount_is_taker_only():
    async with AsyncSessionLocal() as session:
        seller = User(email="clob-seller@example.com", hashed_password="x" * 60)
        taker = User(email="clob-taker@example.com", hashed_password="x" * 60)
        session.add_all([seller, taker])
        await session.flush()
        await collateral.deposit(session, seller, Decimal(10000))
        await collateral.deposit(session, taker, Decimal(10000))

        event = Event(slug="clob-agx", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id,
            condition_id="clob-agx-cond",
            question="q",
            outcomes=["YES", "NO"],
            min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()
        token = OutcomeToken(
            token_id=f"tok-{market.id}",
            market_id=market.id,
            outcome_index=0,
            symbol="YES",
        )
        session.add(token)
        await session.flush()
        await split_position(session, seller, market, Decimal(10))

        await agx.sync_balance(session, taker.id, "1000")
        await agx.stake(session, taker.id, "600")
        await session.flush()

        engine = MatchingEngine()
        await engine.submit_order(
            session, seller.id, market, token, collateral,
            side="SELL", price=Decimal("0.50"), amount=Decimal(10),
        )
        await engine.submit_order(
            session, taker.id, market, token, collateral,
            side="BUY", price=Decimal("0.50"), amount=Decimal(10),
        )
        await session.flush()

        fill = (await session.execute(select(TradeFill))).scalar_one()
        # Base parabolic fee: 10 * 0.02 * 0.50 * (1 - 0.50) = 0.0500
        assert Decimal(fill.maker_fee) == Decimal("0.0500")
        # Tier 1 (600 AGX staked) takes 5 percent off the taker fee only.
        assert Decimal(fill.taker_fee) == Decimal("0.0475")


async def test_clob_fee_is_unchanged_for_zero_agx_taker():
    async with AsyncSessionLocal() as session:
        seller = User(email="clob-zero-seller@example.com", hashed_password="x" * 60)
        taker = User(email="clob-zero-taker@example.com", hashed_password="x" * 60)
        session.add_all([seller, taker])
        await session.flush()
        await collateral.deposit(session, seller, Decimal(10000))
        await collateral.deposit(session, taker, Decimal(10000))

        event = Event(slug="clob-zero", title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id,
            condition_id="clob-zero-cond",
            question="q",
            outcomes=["YES", "NO"],
            min_order_size=Decimal(5),
        )
        session.add(market)
        await session.flush()
        token = OutcomeToken(
            token_id=f"tok-{market.id}",
            market_id=market.id,
            outcome_index=0,
            symbol="YES",
        )
        session.add(token)
        await session.flush()
        await split_position(session, seller, market, Decimal(10))

        engine = MatchingEngine()
        await engine.submit_order(
            session, seller.id, market, token, collateral,
            side="SELL", price=Decimal("0.50"), amount=Decimal(10),
        )
        await engine.submit_order(
            session, taker.id, market, token, collateral,
            side="BUY", price=Decimal("0.50"), amount=Decimal(10),
        )
        await session.flush()

        fill = (await session.execute(select(TradeFill))).scalar_one()
        assert Decimal(fill.maker_fee) == Decimal("0.0500")
        assert Decimal(fill.taker_fee) == Decimal("0.0500")
        assert await agx.peek_balance(session, taker.id) is None
