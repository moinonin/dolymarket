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
            "end_date": "2027-01-01T00:00:00Z",
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
            "end_date": "2027-03-01T00:00:00Z",
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

    # Non-creator cannot edit UNFUNDED market (403)
    r_edit_other = await client.patch(
        f"/api/v4/prediction/community/markets/{created['market_id']}",
        json={"resolution_criteria": "Attempted hijack by non-creator."},
        headers=funder_headers,
    )
    assert r_edit_other.status_code == 403

    # Creator CAN edit UNFUNDED market (200) and clarity updates
    r_edit_ok = await client.patch(
        f"/api/v4/prediction/community/markets/{created['market_id']}",
        json={
            "resolution_criteria": "Resolves YES if CoinGecko daily close >= $300 on or before 2027-03-01 00:00 UTC."
        },
        headers=creator_headers,
    )
    assert r_edit_ok.status_code == 200, r_edit_ok.text
    assert r_edit_ok.json()["clarity"]["score"] >= 75

    # Partial LP deposit ($5, still UNFUNDED) locks market from further edits (409)
    r_partial = await client.post(
        f"/api/v4/prediction/community/markets/{created['market_id']}/fund",
        json={"amount_usdc": 5},
        headers=funder_headers,
    )
    assert r_partial.status_code == 200
    assert r_partial.json()["status"] == "UNFUNDED"

    r_edit_partial = await client.patch(
        f"/api/v4/prediction/community/markets/{created['market_id']}",
        json={"resolution_criteria": "Trying to edit after partial LP deposit."},
        headers=creator_headers,
    )
    assert r_edit_partial.status_code == 409

    # Community member funds remaining $5 ($10 total) -> transitions UNFUNDED -> ACTIVE
    r_fund = await client.post(
        f"/api/v4/prediction/community/markets/{created['market_id']}/fund",
        json={"amount_usdc": 5},
        headers=funder_headers,
    )
    assert r_fund.status_code == 200, r_fund.text
    assert r_fund.json()["status"] == "ACTIVE"
    assert r_fund.json()["liquidity_funded_usdc"] == 10.0

    # Expired market past end_date cannot be funded (409)
    from datetime import UTC, datetime, timedelta
    from app.db.session import AsyncSessionLocal
    from app.models.domain import Event
    from sqlalchemy import update

    async with AsyncSessionLocal() as s:
        await s.execute(
            update(Event)
            .where(Event.slug == created["slug"])
            .values(end_date=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()

    r_expired_fund = await client.post(
        f"/api/v4/prediction/community/markets/{created['market_id']}/fund",
        json={"amount_usdc": 5},
        headers=funder_headers,
    )
    assert r_expired_fund.status_code == 409

    # Once ACTIVE, even creator is blocked from editing (409)
    r_edit_locked = await client.patch(
        f"/api/v4/prediction/community/markets/{created['market_id']}",
        json={"resolution_criteria": "Trying to change rules after funding."},
        headers=creator_headers,
    )
    assert r_edit_locked.status_code == 409

    # While end_date is in the past, order placement is also blocked (409)
    r_order_expired = await client.post(
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
    assert r_order_expired.status_code == 409

    # Restore future end_date -> order placement succeeds
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(Event)
            .where(Event.slug == created["slug"])
            .values(end_date=datetime.now(UTC) + timedelta(days=30))
        )
        await s.commit()

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
