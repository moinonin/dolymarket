"""Tests for Sprint 6.1: Atomic CLOB + LMSR AMM Smart Order Router."""
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_smart_router_splits_clob_and_amm_and_handles_empty_book_exit(client: AsyncClient):
    creator_h = await auth_headers(client, "router_creator@example.com")
    maker_h = await auth_headers(client, "router_maker@example.com")
    taker_h = await auth_headers(client, "router_taker@example.com")

    for h, amt in ((creator_h, 200), (maker_h, 200), (taker_h, 200)):
        r_dep = await client.post("/api/v1/collateral/deposit", json={"amount": amt}, headers=h)
        assert r_dep.status_code == 200

    # Create + fund community market ($50 USDC -> ACTIVE + AmmPool seeded at 0.50)
    r_mk = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Smart Router Test Market",
            "question": "Will smart router split CLOB and AMM?",
            "category": "Crypto",
            "outcomes": ["YES", "NO"],
            "resolution_criteria": "Resolves YES per test.",
            "initial_liquidity_usdc": 50,
        },
        headers=creator_h,
    )
    assert r_mk.status_code == 201, r_mk.text
    mk = r_mk.json()
    market_id = mk["market_id"]
    yes_tok = mk["tokens"][0]["token_id"]

    # Maker buys 5 YES from AMM, then rests a cheap SELL at $0.40 on the CLOB
    r_m_buy = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "BUY", "shares": 5},
        headers=maker_h,
    )
    assert r_m_buy.status_code == 200, r_m_buy.text

    r_m_sell = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market_id,
            "token_id": yes_tok,
            "side": "SELL",
            "type": "LIMIT",
            "price": 0.40,
            "amount": 5,
            "time_in_force": "GTC",
        },
        headers=maker_h,
    )
    assert r_m_sell.status_code == 201, r_m_sell.text

    # Smart quote for BUY 15 YES -> 5 from CLOB @ 0.40 + 10 from AMM
    r_sq = await client.post(
        "/api/v4/prediction/orders/smart-quote",
        json={"market_id": market_id, "token_id": yes_tok, "side": "BUY", "shares": 15},
    )
    assert r_sq.status_code == 200, r_sq.text
    sq = r_sq.json()
    assert sq["clob_shares"] == 5.0
    assert sq["amm_shares"] == 10.0
    assert sq["clob_exhausted"] is True

    # Execute atomic smart BUY 15 YES
    r_exec = await client.post(
        "/api/v4/prediction/orders/smart",
        json={"market_id": market_id, "token_id": yes_tok, "side": "BUY", "shares": 15},
        headers=taker_h,
    )
    assert r_exec.status_code == 201, r_exec.text
    ex = r_exec.json()
    assert ex["status"] == "FILLED"
    assert ex["clob_filled_shares"] == 5.0
    assert ex["amm_filled_shares"] == 10.0
    assert ex["total_filled_shares"] == 15.0

    # Now CLOB has 0 bids -> smart SELL 5 YES routes 100% to AMM backstop
    r_exit = await client.post(
        "/api/v4/prediction/orders/smart",
        json={"market_id": market_id, "token_id": yes_tok, "side": "SELL", "shares": 5},
        headers=taker_h,
    )
    assert r_exit.status_code == 201, r_exit.text
    ex2 = r_exit.json()
    assert ex2["status"] == "FILLED"
    assert ex2["clob_filled_shares"] == 0.0
    assert ex2["amm_filled_shares"] == 5.0
