"""Tests for Community Prediction Markets (tier, UNFUNDED state, safeguards, funding)."""
from __future__ import annotations

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_community_market_unfunded_blocks_trades_until_funded(client):
    creator_headers = await auth_headers(client, "comm_creator@example.com")
    funder_headers = await auth_headers(client, "comm_funder@example.com")

    # Prohibited category rejected
    r_bad = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Bad Market",
            "question": "Should this be blocked?",
            "category": "assassination",
            "resolution_criteria": "Blocked by safeguard rules.",
        },
        headers=creator_headers,
    )
    assert r_bad.status_code == 400

    # Create unfunded community market
    r_create = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "SOL $300 by Q1 2027",
            "question": "Will SOL reach $300 before March 2027?",
            "category": "Crypto",
            "resolution_criteria": "Resolves YES if CoinGecko daily close >= $300.",
            "initial_liquidity_usdc": 0,
        },
        headers=creator_headers,
    )
    assert r_create.status_code == 201, r_create.text
    created = r_create.json()
    assert created["tier"] == "COMMUNITY"
    assert created["status"] == "UNFUNDED"

    # Tier filter returns it
    r_list = await client.get("/api/v4/prediction/events?tier=COMMUNITY")
    assert r_list.status_code == 200
    assert any(e["slug"] == created["slug"] for e in r_list.json()["events"])

    # Trading on UNFUNDED market is blocked (409)
    await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=funder_headers)
    r_order = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": created["market_id"],
            "token_id": created["tokens"][0]["token_id"],
            "side": "BUY",
            "price": "0.50",
            "amount": "5",
        },
        headers=funder_headers,
    )
    assert r_order.status_code == 409

    # Community member funds $10 -> transitions UNFUNDED -> ACTIVE
    r_fund = await client.post(
        f"/api/v4/prediction/community/markets/{created['market_id']}/fund",
        json={"amount_usdc": 10},
        headers=funder_headers,
    )
    assert r_fund.status_code == 200, r_fund.text
    assert r_fund.json()["status"] == "ACTIVE"
    assert r_fund.json()["liquidity_funded_usdc"] == 10.0

    # Now order placement succeeds
    r_order_ok = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": created["market_id"],
            "token_id": created["tokens"][0]["token_id"],
            "side": "BUY",
            "price": "0.50",
            "amount": "5",
        },
        headers=funder_headers,
    )
    assert r_order_ok.status_code in (200, 201), r_order_ok.text
