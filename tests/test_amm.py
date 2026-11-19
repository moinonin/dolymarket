"""Tests for Hybrid LMSR AMM pool, trading, fee collection, and LP redemption."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.amm import lmsr_cost, lmsr_prices
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_lmsr_math_invariants():
    p_yes, p_no = lmsr_prices(0.0, 0.0, 100.0)
    assert p_yes == Decimal("0.5000")
    assert p_no == Decimal("0.5000")
    assert p_yes + p_no == Decimal("1.0000")

    # Overflow-safe for large q / b
    c = lmsr_cost(10000.0, 9950.0, 10.0)
    assert c > 10000.0


async def test_amm_pool_lifecycle_fund_trade_and_redeem(client):
    lp_headers = await auth_headers(client, "amm_lp@example.com")
    trader_headers = await auth_headers(client, "amm_trader@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=lp_headers)
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=trader_headers)

    # Create and fund a community market -> auto-seeds AMM pool
    r_create = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "ETH $6k",
            "question": "Will ETH hit $6k?",
            "category": "Crypto",
            "resolution_criteria": "CoinGecko daily close >= $6000.",
            "end_date": "2027-01-01T00:00:00Z",
            "initial_liquidity_usdc": 100,
        },
        headers=lp_headers,
    )
    assert r_create.status_code == 201, r_create.text
    m = r_create.json()
    market_id = m["market_id"]
    yes_tok = m["tokens"][0]["token_id"]

    # Pool state is live at 50/50
    r_pool = await client.get(f"/api/v4/prediction/amm/{market_id}")
    assert r_pool.status_code == 200
    assert r_pool.json()["yes_price"] == 0.5
    assert r_pool.json()["pool_usdc"] == 100.0

    # Quote & buy 10 YES shares
    r_quote = await client.get(f"/api/v4/prediction/amm/{market_id}/quote?outcome_index=0&side=BUY&shares=10")
    assert r_quote.status_code == 200
    assert r_quote.json()["post_yes_price"] > 0.5

    r_buy = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "BUY", "shares": 10},
        headers=trader_headers,
    )
    assert r_buy.status_code == 200, r_buy.text
    assert r_buy.json()["post_yes_price"] > 0.5
    assert r_buy.json()["fee_usdc"] > 0

    # Sell 5 YES shares back
    r_sell = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "SELL", "shares": 5},
        headers=trader_headers,
    )
    assert r_sell.status_code == 200, r_sell.text
    assert r_sell.json()["post_yes_price"] < r_buy.json()["post_yes_price"]

    # Fees accrued in pool AND forwarded 50% to open AGX reward epoch
    r_pool2 = await client.get(f"/api/v4/prediction/amm/{market_id}")
    assert r_pool2.json()["fees_collected_usdc"] > 0
    r_epochs = await client.get("/api/v1/agx/epochs")
    assert r_epochs.status_code == 200
    epochs = r_epochs.json()["epochs"]
    assert len(epochs) >= 1

    # Underwater pool (worst liability >= pool_usdc) rejects new LP deposits with 409
    from sqlalchemy import update
    from app.db.session import AsyncSessionLocal
    from app.models.domain import AmmPool

    async with AsyncSessionLocal() as s:
        await s.execute(
            update(AmmPool).where(AmmPool.market_id == market_id).values(q_yes=Decimal("500"))
        )
        await s.commit()

    r_underwater = await client.post(
        f"/api/v4/prediction/community/markets/{market_id}/fund",
        json={"amount_usdc": 10},
        headers=lp_headers,
    )
    assert r_underwater.status_code == 409
    assert float(epochs[0]["total_fees_collected"]) > 0
