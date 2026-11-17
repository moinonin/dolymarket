"""Automated market resolution worker & endpoint tests."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models.domain import Event, Market, OracleDispute, User
from app.services.resolution_worker import run_resolution_tick


@pytest.mark.asyncio
async def test_resolution_worker_lifecycle_close_propose_finalize():
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        expired_event = Event(
            slug="expired-btc-100k",
            title="BTC above 100k",
            category="Crypto",
            status="ACTIVE",
            end_date=now - timedelta(minutes=5),
        )
        future_event = Event(
            slug="future-eth-10k",
            title="ETH above 10k",
            category="Crypto",
            status="ACTIVE",
            end_date=now + timedelta(days=5),
        )
        session.add_all([expired_event, future_event])
        await session.flush()

        expired_market = Market(
            event_id=expired_event.id,
            condition_id="0xexpired1",
            question="Will BTC >= 100k?",
            outcomes=["YES", "NO"],
            status="ACTIVE",
            oracle_feed="static:120000",
            oracle_threshold=Decimal(100000),
            oracle_comparator=">=",
        )
        future_market = Market(
            event_id=future_event.id,
            condition_id="0xfuture1",
            question="Will ETH >= 10k?",
            outcomes=["YES", "NO"],
            status="ACTIVE",
            oracle_feed="static:3500",
            oracle_threshold=Decimal(10000),
            oracle_comparator=">=",
        )
        session.add_all([expired_market, future_market])
        await session.commit()
        expired_id = expired_market.id
        future_id = future_market.id

    # Tick 1: closes expired_market and proposes resolution immediately via static oracle
    async with AsyncSessionLocal() as session:
        r1 = await run_resolution_tick(session, now=now)
        await session.commit()
        assert r1["closed"] == 1
        assert r1["proposed"] == 1
        assert r1["finalized"] == 0

    # Tick 2 immediately after: idempotent (nothing double-proposed or finalized before deadline)
    async with AsyncSessionLocal() as session:
        r2 = await run_resolution_tick(session, now=now + timedelta(minutes=5))
        await session.commit()
        assert r2["closed"] == 0
        assert r2["proposed"] == 0
        assert r2["finalized"] == 0

        m = (await session.execute(select(Market).where(Market.id == expired_id))).scalar_one()
        fm = (await session.execute(select(Market).where(Market.id == future_id))).scalar_one()
        assert m.status == "IN_RESOLUTION"
        assert fm.status == "ACTIVE"

    # Tick 3 after 2h dispute window expires: finalizes uncontested market
    async with AsyncSessionLocal() as session:
        r3 = await run_resolution_tick(session, now=now + timedelta(hours=3))
        await session.commit()
        assert r3["finalized"] == 1

        m = (await session.execute(select(Market).where(Market.id == expired_id))).scalar_one()
        assert m.status == "RESOLVED"
        assert m.winning_outcome_index == 0


@pytest.mark.asyncio
async def test_resolution_worker_skips_disputed_markets():
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        ev = Event(
            slug="disputed-ev",
            title="Disputed Event",
            category="Crypto",
            status="CLOSED",
            end_date=now - timedelta(hours=4),
        )
        session.add(ev)
        await session.flush()

        mkt = Market(
            event_id=ev.id,
            condition_id="0xdisputed1",
            question="Disputed market?",
            outcomes=["YES", "NO"],
            status="DISPUTED",
        )
        session.add(mkt)
        await session.flush()

        dispute = OracleDispute(
            market_id=mkt.id,
            proposed_outcome_index=0,
            proposer_address="auto-oracle:static:1",
            bond_amount=Decimal(50),
            dispute_deadline=now - timedelta(hours=1),
            status="DISPUTED",
        )
        session.add(dispute)
        await session.commit()
        mkt_id = mkt.id

    async with AsyncSessionLocal() as session:
        r = await run_resolution_tick(session, now=now)
        await session.commit()
        assert r["finalized"] == 0
        m = (await session.execute(select(Market).where(Market.id == mkt_id))).scalar_one()
        assert m.status == "DISPUTED"
        assert m.winning_outcome_index is None


@pytest.mark.asyncio
async def test_community_market_and_admin_run_tick_endpoints(client):
    async with AsyncSessionLocal() as session:
        admin = User(
            email="admin-res@example.com",
            hashed_password="x",
            is_admin=True,
        )
        session.add(admin)
        await session.commit()
        admin_id = admin.id

    token = create_access_token(admin_id, "admin-res@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v4/prediction/community/markets",
        headers=headers,
        json={
            "title": "Community Auto Market",
            "question": "Will BTC close >= 100k?",
            "category": "Crypto",
            "resolution_criteria": "Gate BTC_USDT spot >= 100000 UTC deadline 2026.",
            "outcomes": ["YES", "NO"],
            "end_date": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "oracle_feed": "gate:BTC_USDT",
            "oracle_threshold": 100000,
            "oracle_comparator": ">=",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["oracle_feed"] == "gate:BTC_USDT"
    assert data["oracle_threshold"] == 100000.0
    assert data["oracle_comparator"] == ">="

    # Community creator cannot rig outcome with static: or malformed feeds
    bad_static = await client.post(
        "/api/v4/prediction/community/markets",
        headers=headers,
        json={
            "title": "Rigged Static Market",
            "question": "Will static win?",
            "category": "Crypto",
            "resolution_criteria": "Static feed test criteria with sufficient length.",
            "oracle_feed": "static:999999",
            "oracle_threshold": 100,
        },
    )
    assert bad_static.status_code == 422

    bad_malformed = await client.post(
        "/api/v4/prediction/community/markets",
        headers=headers,
        json={
            "title": "Malformed Feed Market",
            "question": "Will nonsense win?",
            "category": "Crypto",
            "resolution_criteria": "Malformed feed test criteria with sufficient length.",
            "oracle_feed": "nonsense",
            "oracle_threshold": 100,
        },
    )
    assert bad_malformed.status_code == 422

    missing_threshold = await client.post(
        "/api/v4/prediction/community/markets",
        headers=headers,
        json={
            "title": "Missing Threshold Market",
            "question": "Will BTC win?",
            "category": "Crypto",
            "resolution_criteria": "Missing threshold test criteria with sufficient length.",
            "oracle_feed": "gate:BTC_USDT",
        },
    )
    assert missing_threshold.status_code == 422

    tick_resp = await client.post(
        "/api/v4/prediction/resolution/run-tick",
        headers=headers,
    )
    assert tick_resp.status_code == 200
    assert tick_resp.json() == {"closed": 0, "expired": 0, "proposed": 0, "finalized": 0}


@pytest.mark.asyncio
async def test_h4_second_lp_deposit_preserves_lmsr_price():
    from app.models.domain import AmmPool, CollateralAccount, OutcomeToken
    from app.services import amm

    async with AsyncSessionLocal() as session:
        lp1 = User(email="lp1@example.com", hashed_password="x")
        lp2 = User(email="lp2@example.com", hashed_password="x")
        trader = User(email="trader_h4@example.com", hashed_password="x")
        session.add_all([lp1, lp2, trader])
        await session.flush()

        session.add_all([
            CollateralAccount(user_id=lp1.id, balance=Decimal(500)),
            CollateralAccount(user_id=lp2.id, balance=Decimal(500)),
            CollateralAccount(user_id=trader.id, balance=Decimal(500)),
        ])
        ev = Event(slug="h4-ev", title="H4 Event", category="Crypto", status="ACTIVE")
        session.add(ev)
        await session.flush()

        mkt = Market(
            event_id=ev.id,
            condition_id="0xh4mkt",
            question="H4 test?",
            outcomes=["YES", "NO"],
            status="ACTIVE",
        )
        session.add(mkt)
        await session.flush()

        yes_tok = OutcomeToken(
            token_id="0xh4mkt-0", market_id=mkt.id, outcome_index=0, symbol="YES"
        )
        no_tok = OutcomeToken(
            token_id="0xh4mkt-1", market_id=mkt.id, outcome_index=1, symbol="NO"
        )
        session.add_all([yes_tok, no_tok])
        await session.flush()

        await amm.deposit_liquidity(session, mkt, lp1.id, Decimal(100))
        await amm.execute_amm_trade(session, mkt, yes_tok, trader.id, "BUY", Decimal(150))

        pool = (await session.execute(select(AmmPool).where(AmmPool.market_id == mkt.id))).scalar_one()
        p_before, _ = amm.lmsr_prices(float(pool.q_yes), float(pool.q_no), float(pool.b))

        await amm.deposit_liquidity(session, mkt, lp2.id, Decimal(100))
        p_after, _ = amm.lmsr_prices(float(pool.q_yes), float(pool.q_no), float(pool.b))
        assert abs(p_after - p_before) <= Decimal("0.0005")
        assert Decimal(str(pool.q_yes)) == Decimal("150.0000")

        mkt.status = "RESOLVED"
        mkt.winning_outcome_index = 0
        await session.flush()
        r1 = await amm.redeem_lp(session, mkt, lp1.id)
        r2 = await amm.redeem_lp(session, mkt, lp2.id)
        assert r1["payout_usdc"] > 0 and r2["payout_usdc"] > 0


@pytest.mark.asyncio
async def test_h5_unfunded_expired_market_refunds_partial_lp():
    from app.models.domain import CollateralAccount
    from app.services import amm

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        lp = User(email="lp_h5@example.com", hashed_password="x")
        session.add(lp)
        await session.flush()
        acc = CollateralAccount(user_id=lp.id, balance=Decimal(50))
        session.add(acc)
        ev = Event(
            slug="h5-ev",
            title="H5 Event",
            category="Crypto",
            status="UNFUNDED",
            end_date=now - timedelta(minutes=1),
        )
        session.add(ev)
        await session.flush()
        mkt = Market(
            event_id=ev.id,
            condition_id="0xh5mkt",
            question="H5 unfunded?",
            outcomes=["YES", "NO"],
            status="UNFUNDED",
            tier="COMMUNITY",
        )
        session.add(mkt)
        await session.flush()

        await amm.deposit_liquidity(session, mkt, lp.id, Decimal(5))
        await session.commit()
        lp_id = lp.id
        mkt_id = mkt.id

    async with AsyncSessionLocal() as session:
        res = await run_resolution_tick(session, now=now)
        await session.commit()
        assert res["expired"] == 1

        mkt = (await session.execute(select(Market).where(Market.id == mkt_id))).scalar_one()
        acc = (await session.execute(select(CollateralAccount).where(CollateralAccount.user_id == lp_id))).scalar_one()
        assert mkt.status == "EXPIRED"
        assert Decimal(str(acc.balance)) == Decimal("50.0000")


@pytest.mark.asyncio
async def test_m1_m2_m6_m7_community_validation_and_m5_agx_dispute(client):
    from app.models.domain import AgxBalance

    async with AsyncSessionLocal() as session:
        admin = User(email="admin_m5@example.com", hashed_password="x", is_admin=True)
        trader = User(email="trader_m5@example.com", hashed_password="x", is_admin=False)
        session.add_all([admin, trader])
        await session.flush()
        session.add(AgxBalance(user_id=trader.id, balance=Decimal(150)))
        await session.commit()
        admin_id, trader_id = admin.id, trader.id

    admin_h = {"Authorization": f"Bearer {create_access_token(admin_id, 'admin_m5@example.com')}"}
    trader_h = {"Authorization": f"Bearer {create_access_token(trader_id, 'trader_m5@example.com')}"}
    base = {
        "title": "Valid Market Title",
        "question": "Will BTC pass 100k?",
        "resolution_criteria": "Resolves YES if Gate BTC_USDT >= 100000 UTC.",
    }

    # M1: invalid end_date -> 422 (never 500)
    assert (await client.post("/api/v4/prediction/community/markets", headers=trader_h, json={**base, "end_date": "not-a-date"})).status_code == 422
    # M2: past end_date -> 422
    assert (await client.post("/api/v4/prediction/community/markets", headers=trader_h, json={**base, "end_date": (datetime.now(UTC) - timedelta(days=1)).isoformat()})).status_code == 422
    # M6: prohibited substring -> 400
    assert (await client.post("/api/v4/prediction/community/markets", headers=trader_h, json={**base, "category": "Violence & Crime"})).status_code == 400
    # M7: 3 outcomes -> 422
    assert (await client.post("/api/v4/prediction/community/markets", headers=trader_h, json={**base, "outcomes": ["A", "B", "C"]})).status_code == 422

    # M5: non-admin trader with AGX can dispute, locking 100 AGX, and finalize upholds & rewards
    async with AsyncSessionLocal() as session:
        ev = Event(slug="m5-ev", title="M5 Event", category="Crypto", status="CLOSED")
        session.add(ev)
        await session.flush()
        mkt = Market(event_id=ev.id, condition_id="0xm5mkt", question="M5?", outcomes=["YES", "NO"], status="CLOSED")
        session.add(mkt)
        await session.commit()
        mkt_id = mkt.id

    assert (await client.post("/api/v4/prediction/resolution/propose", headers=admin_h, json={"market_id": mkt_id, "proposed_outcome_index": 0})).status_code == 200
    d_resp = await client.post("/api/v4/prediction/resolution/dispute", headers=trader_h, json={"market_id": mkt_id, "counter_bond": 100})
    assert d_resp.status_code == 200, d_resp.text
    assert d_resp.json()["market_status"] == "DISPUTED"

    # Admin overturns proposal (winning=1 != proposed=0 -> upheld, +20% reward -> 170 AGX)
    f_resp = await client.post("/api/v4/prediction/resolution/finalize", headers=admin_h, json={"market_id": mkt_id, "winning_outcome_index": 1})
    assert f_resp.status_code == 200
    async with AsyncSessionLocal() as session:
        bal = (await session.execute(select(AgxBalance).where(AgxBalance.user_id == trader_id))).scalar_one()
        assert Decimal(str(bal.locked_dispute_balance)) == Decimal(0)
        assert Decimal(str(bal.balance)) == Decimal(170)
