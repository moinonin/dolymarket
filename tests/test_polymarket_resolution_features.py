"""A-to-Z tests for Polymarket-style resolution upgrades:
1. Immutable SHA-256 rules_hash (ancillaryData parity)
2. Single re-proposal (REPROPOSED) + append-only updates[] audit trail
3. 50/50 INVALID / CANCELLED settlement payout ($0.50 YES / $0.50 NO + AMM LP conservation)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.domain import AgxBalance, Market
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def _admin_headers(client, email: str = "poly_admin@example.com") -> dict:
    h = await auth_headers(client, email)
    await make_admin(email)
    return h


async def _credit_agx(email: str, amount: Decimal) -> None:
    from app.models.domain import User

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        bal = (
            await session.execute(select(AgxBalance).where(AgxBalance.user_id == user.id))
        ).scalar_one_or_none()
        if bal is None:
            bal = AgxBalance(user_id=user.id, balance=amount, staked_balance=Decimal("0"))
            session.add(bal)
        else:
            bal.balance = Decimal(str(bal.balance)) + amount
        await session.commit()


async def test_rules_hash_and_single_reproposal_with_audit_trail(client):
    adm = await _admin_headers(client, "poly_adm1@example.com")
    u = await auth_headers(client, "poly_user1@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=u)
    await _credit_agx("poly_user1@example.com", Decimal("500"))

    # 1. Create unfunded market -> rules_hash returned
    r_c = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Rules Hash Test",
            "question": "Will event X occur before 2027?",
            "category": "Politics",
            "resolution_criteria": "Resolves Yes if Reuters reports event X.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 0,
        },
        headers=u,
    )
    assert r_c.status_code == 201, r_c.text
    m = r_c.json()
    h1 = m["rules_hash"]
    assert h1.startswith("0x") and len(h1) == 66

    # Editing unfunded market changes rules_hash
    r_p = await client.patch(
        f"/api/v4/prediction/community/markets/{m['market_id']}",
        json={"resolution_criteria": "Resolves Yes if Reuters or AP reports event X."},
        headers=u,
    )
    assert r_p.status_code == 200, r_p.text
    h2 = r_p.json()["rules_hash"]
    assert h2 != h1

    # Fund & close market
    await client.post(
        f"/api/v4/prediction/community/markets/{m['market_id']}/fund",
        json={"amount_usdc": 50},
        headers=u,
    )
    async with AsyncSessionLocal() as session:
        mkt = (await session.execute(select(Market).where(Market.id == m["market_id"]))).scalar_one()
        mkt.status = "CLOSED"
        await session.commit()

    # 2. Propose YES (index 0) -> rules_hash locked in dispute + updates=[PROPOSED]
    r_prop = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": m["market_id"], "proposed_outcome_index": 0},
        headers=adm,
    )
    assert r_prop.status_code == 200, r_prop.text
    assert r_prop.json()["rules_hash"] == h2
    assert [u_ev["event"] for u_ev in r_prop.json()["updates"]] == ["PROPOSED"]

    # 3. First dispute (100 AGX)
    r_d1 = await client.post(
        "/api/v4/prediction/resolution/dispute",
        json={"market_id": m["market_id"], "counter_bond": 100},
        headers=u,
    )
    assert r_d1.status_code == 200, r_d1.text

    # 4. Single re-proposal to NO (index 1) -> succeeds and opens fresh window
    r_rep = await client.post(
        "/api/v4/prediction/resolution/repropose",
        json={
            "market_id": m["market_id"],
            "reproposed_outcome_index": 1,
            "note": "Corrected after primary source review",
        },
        headers=adm,
    )
    assert r_rep.status_code == 200, r_rep.text
    rep_data = r_rep.json()
    assert rep_data["market_status"] == "IN_RESOLUTION"
    assert rep_data["reproposed_outcome_index"] == 1
    assert [u_ev["event"] for u_ev in rep_data["updates"]] == [
        "PROPOSED",
        "DISPUTED",
        "REPROPOSED",
    ]

    # Public /resolution/markets exposes rules_hash, was_disputed, reproposed_outcome_index, updates
    r_list = await client.get("/api/v4/prediction/resolution/markets")
    assert r_list.status_code == 200
    row = next(x for x in r_list.json()["markets"] if x["market_id"] == m["market_id"])
    assert row["rules_hash"] == h2
    assert row["was_disputed"] is True
    assert row["reproposed_outcome_index"] == 1
    assert len(row["updates"]) == 3

    # 5. Second dispute -> blocks a second re-proposal (409: must finalize directly)
    r_d2 = await client.post(
        "/api/v4/prediction/resolution/dispute",
        json={"market_id": m["market_id"], "counter_bond": 100},
        headers=u,
    )
    assert r_d2.status_code == 200, r_d2.text

    r_rep2 = await client.post(
        "/api/v4/prediction/resolution/repropose",
        json={"market_id": m["market_id"], "reproposed_outcome_index": 0},
        headers=adm,
    )
    assert r_rep2.status_code == 409, r_rep2.text


async def test_invalid_50_50_settlement_payout_and_amm_lp_conservation(client):
    adm = await _admin_headers(client, "poly_adm2@example.com")
    lp_h = await auth_headers(client, "poly_lp@example.com")
    tr_h = await auth_headers(client, "poly_tr@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=lp_h)
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=tr_h)

    r_c = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Cancelled Championship",
            "question": "Will Team A win the 2027 Cup?",
            "category": "Sports",
            "resolution_criteria": "Resolves Yes if Team A wins.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 100,
        },
        headers=lp_h,
    )
    assert r_c.status_code == 201, r_c.text
    m = r_c.json()
    mid = m["market_id"]
    yes_tok = m["tokens"][0]["token_id"]

    # Trader buys 20 YES shares from AMM
    r_buy = await client.post(
        f"/api/v4/prediction/amm/{mid}/trade",
        json={"token_id": yes_tok, "side": "BUY", "shares": 20},
        headers=tr_h,
    )
    assert r_buy.status_code == 200, r_buy.text

    # Close, propose, and finalize as INVALID / CANCELLED (50/50 split)
    async with AsyncSessionLocal() as session:
        mkt = (await session.execute(select(Market).where(Market.id == mid))).scalar_one()
        mkt.status = "CLOSED"
        await session.commit()

    await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": mid, "proposed_outcome_index": 0},
        headers=adm,
    )
    r_fin = await client.post(
        "/api/v4/prediction/resolution/finalize",
        json={"market_id": mid, "winning_outcome_index": -1, "resolve_invalid": True},
        headers=adm,
    )
    assert r_fin.status_code == 200, r_fin.text
    assert r_fin.json()["winning_outcome_index"] == -1
    assert r_fin.json()["resolved_invalid"] is True

    # Trader redeems 20 YES shares -> must receive $10.00 (20 * $0.50)
    r_pos = await client.get("/api/v4/prediction/positions", headers=tr_h)
    pos_id = next(p["position_id"] for p in r_pos.json()["positions"] if p["market_id"] == mid)
    r_red = await client.post(f"/api/v4/prediction/positions/{pos_id}/redeem", headers=tr_h)
    assert r_red.status_code == 200, r_red.text
    assert float(r_red.json()["payout_amount"]) == pytest.approx(10.0, abs=0.01)

    # LP redeems pool -> liability is 20 * 0.50 = $10.00, so LP gets pool_usdc - $10.00
    r_lp = await client.post(f"/api/v4/prediction/amm/{mid}/redeem", headers=lp_h)
    assert r_lp.status_code == 200, r_lp.text
    assert float(r_lp.json()["payout_usdc"]) > 100.0
