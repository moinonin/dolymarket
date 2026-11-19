"""Tests for Sprint 6.2: Oracle Clarity Score & Deterministic Resolution Feeds."""
import pytest
from httpx import AsyncClient

from app.services.oracle import compute_clarity_score
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def test_clarity_score_high_vs_low():
    high = compute_clarity_score(
        "Resolves YES if Gate BTC_USDT spot >= 100000 at 2026-12-31 23:59 UTC per https://api.gateio.ws.",
        oracle_feed="gate:BTC_USDT",
    )
    assert high["grade"] == "HIGH"
    assert high["score"] == 100
    assert high["flags"] == []

    low = compute_clarity_score("Maybe goes up soon, subjective vibes")
    assert low["grade"] == "LOW"
    assert low["score"] < 50
    assert len(low["flags"]) >= 3

    # Paraphrased market without static keyword-list tokens (caught by dolymarket-s1)
    paraphrased = compute_clarity_score(
        "This market resolves based on the Bureau of Economic Analysis quarterly GDP release "
        "scheduled at the end of Q3; outcome is determined by whether annualized growth is positive.",
        question="Will US Q3 GDP growth be positive?",
    )
    assert paraphrased["engine"] == "dolymarket_s1"
    assert paraphrased["score"] >= 75
    assert paraphrased["category"] == "Macro"

    # Open-ended Who/Which with binary YES/NO, "any exchange", and unanchored "next" are flagged
    bad_framing = compute_clarity_score(
        "Resolves YES if price hits $150,000 on any exchange before the next meeting.",
        question="Who will win the next NBA championship?",
        outcomes=["YES", "NO"],
    )
    assert bad_framing["score"] <= 25
    assert any("Open-ended" in f for f in bad_framing["flags"])
    assert any("any exchange" in f for f in bad_framing["flags"])
    assert any("Relative timeframe" in f for f in bad_framing["flags"])


async def test_deterministic_feed_resolution_and_evidence(client: AsyncClient):
    admin_h = await auth_headers(client, "oracle_admin@example.com")
    await make_admin("oracle_admin@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 25}, headers=admin_h)

    r_mk = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "BTC 90k Oracle Feed",
            "question": "Will BTC close >= $90,000 UTC?",
            "category": "Crypto",
            "outcomes": ["YES", "NO"],
            "resolution_criteria": "Resolves YES if Gate BTC_USDT >= 90000 at 2026-12-01 00:00 UTC.",
            "end_date": "2027-01-01T00:00:00Z",
            "oracle_feed": "gate:BTC_USDT",
            "oracle_threshold": 90000,
            "initial_liquidity_usdc": 20,
        },
        headers=admin_h,
    )
    assert r_mk.status_code == 201, r_mk.text
    mk = r_mk.json()
    assert mk["clarity"]["grade"] == "HIGH"
    market_id = mk["market_id"]

    # Close market so oracle resolution can be proposed
    r_close = await client.post(
        f"/api/v4/prediction/admin/markets/{market_id}/close",
        headers=admin_h,
    )
    assert r_close.status_code == 200, r_close.text

    # Resolve via deterministic static feed (95000 >= 90000 -> YES / index 0)
    r_res = await client.post(
        "/api/v4/prediction/resolution/resolve-feed",
        json={
            "market_id": market_id,
            "feed": "static:95000",
            "threshold": 90000,
            "comparator": ">=",
            "auto_finalize": False,
        },
        headers=admin_h,
    )
    assert r_res.status_code == 200, r_res.text
    res = r_res.json()
    assert res["winning_outcome_index"] == 0
    assert res["evidence"]["observed_value"] == 95000.0

    # Public resolution list includes structured evidence
    r_list = await client.get("/api/v4/prediction/resolution/markets")
    assert r_list.status_code == 200
    rows = [m for m in r_list.json()["markets"] if m["market_id"] == market_id]
    assert len(rows) == 1
    assert rows[0]["evidence"]["feed"] == "static:95000"

    # Live clarity-preview endpoint works for community market form
    r_prev = await client.post(
        "/api/v4/prediction/community/clarity-preview",
        json={
            "question": "Will US Q3 GDP growth be positive?",
            "resolution_criteria": (
                "This market resolves based on the Bureau of Economic Analysis quarterly GDP release "
                "scheduled at the end of Q3; outcome is determined by whether annualized growth is positive."
            ),
        },
    )
    assert r_prev.status_code == 200
    prev = r_prev.json()
    assert prev["engine"] == "dolymarket_s1"
    assert prev["score"] >= 75
    assert prev["category"] == "Macro"
