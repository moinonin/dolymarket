"""A-to-Z regression tests for docs/NEON_AUDIT.md CRITICAL + HIGH findings (#1-#9, #11)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.domain import Event, Market
from app.services.oracle_verifier import fetch_source_text
from app.services.resolution_worker import run_resolution_tick
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def _admin_headers(client, email: str = "neon_admin@example.com") -> dict:
    h = await auth_headers(client, email)
    await make_admin(email)
    return h


async def _create_funded_community_market(client, headers, *, title: str = "Audit Market", end_date: str = "2027-06-01T00:00:00Z", resolution_criteria: str = "Resolves Yes if official source confirms.") -> dict:
    r = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": title,
            "question": f"Will {title} happen?",
            "category": "Crypto",
            "resolution_criteria": resolution_criteria,
            "end_date": end_date,
            "initial_liquidity_usdc": 100,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Finding #1 (CRITICAL): Post-Expiry Trading & 30s Sniping Exploit
# ---------------------------------------------------------------------------
async def test_vuln1_post_expiry_trading_blocked_across_amm_clob_smart_and_split(client):
    h = await auth_headers(client, "vuln1_trader@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=h)
    m = await _create_funded_community_market(client, h, title="Expiry Snipe Test")
    market_id = m["market_id"]
    yes_tok = m["tokens"][0]["token_id"]

    # Simulate end_date passing BEFORE the 30s resolution_worker tick closes the market
    async with AsyncSessionLocal() as session:
        ev = (await session.execute(select(Event).where(Event.id == m["event_id"]))).scalar_one()
        ev.end_date = datetime.now(UTC) - timedelta(seconds=10)
        await session.commit()

    # 1. AMM trade blocked (409)
    r_amm = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "BUY", "shares": 5},
        headers=h,
    )
    assert r_amm.status_code == 409, r_amm.text

    # 2. CLOB order blocked (409)
    r_clob = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": market_id, "token_id": yes_tok, "side": "BUY", "price": "0.50", "amount": "5"},
        headers=h,
    )
    assert r_clob.status_code == 409, r_clob.text

    # 3. Smart-order quote & execute blocked (409)
    r_sq = await client.post(
        "/api/v4/prediction/orders/smart-quote",
        json={"market_id": market_id, "token_id": yes_tok, "side": "BUY", "shares": "5"},
        headers=h,
    )
    assert r_sq.status_code == 409, r_sq.text

    r_se = await client.post(
        "/api/v4/prediction/orders/smart",
        json={"market_id": market_id, "token_id": yes_tok, "side": "BUY", "shares": "5"},
        headers=h,
    )
    assert r_se.status_code == 409, r_se.text

    # 4. CTF split blocked (409)
    r_split = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market_id, "shares": "5"},
        headers=h,
    )
    assert r_split.status_code == 409, r_split.text


# ---------------------------------------------------------------------------
# Finding #2 (CRITICAL): AMM agx_fee Double-Counted in pool_usdc
# ---------------------------------------------------------------------------
async def test_vuln2_amm_pool_usdc_does_not_double_count_agx_fee(client):
    lp_h = await auth_headers(client, "vuln2_lp@example.com")
    tr_h = await auth_headers(client, "vuln2_tr@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=lp_h)
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=tr_h)

    m = await _create_funded_community_market(client, lp_h, title="Fee Conservation")
    market_id = m["market_id"]
    yes_tok = m["tokens"][0]["token_id"]

    # BUY 20 shares: pool_usdc must increase by notional + lp_fee (NOT notional + full fee)
    r_buy = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "BUY", "shares": 20},
        headers=tr_h,
    )
    assert r_buy.status_code == 200, r_buy.text
    q_buy = r_buy.json()
    notional = Decimal(str(q_buy["notional_usdc"]))
    fee = Decimal(str(q_buy["fee_usdc"]))
    lp_fee = (fee * Decimal("0.5")).quantize(Decimal("0.0001"))
    agx_fee = (fee - lp_fee).quantize(Decimal("0.0001"))
    assert agx_fee > 0

    pool_after_buy = (await client.get(f"/api/v4/prediction/amm/{market_id}")).json()
    expected_pool_buy = (Decimal("100.0000") + notional + lp_fee).quantize(Decimal("0.0001"))
    assert abs(Decimal(str(pool_after_buy["pool_usdc"])) - expected_pool_buy) <= Decimal("0.0002")

    # SELL 10 shares back: pool_usdc must decrease by notional_sell - lp_fee_sell
    r_sell = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "SELL", "shares": 10},
        headers=tr_h,
    )
    assert r_sell.status_code == 200, r_sell.text
    q_sell = r_sell.json()
    sell_notional = Decimal(str(q_sell["notional_usdc"]))
    sell_fee = Decimal(str(q_sell["fee_usdc"]))
    sell_lp_fee = (sell_fee * Decimal("0.5")).quantize(Decimal("0.0001"))

    pool_after_sell = (await client.get(f"/api/v4/prediction/amm/{market_id}")).json()
    expected_pool_sell = (
        Decimal(str(pool_after_buy["pool_usdc"])) - (sell_notional - sell_lp_fee)
    ).quantize(Decimal("0.0001"))
    assert abs(Decimal(str(pool_after_sell["pool_usdc"])) - expected_pool_sell) <= Decimal("0.0002")


# ---------------------------------------------------------------------------
# Finding #3 (CRITICAL): Negative q_yes / q_no AMM Sell Exploit
# ---------------------------------------------------------------------------
async def test_vuln3_amm_blocks_selling_more_shares_than_pool_issued(client):
    h = await auth_headers(client, "vuln3_attacker@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=h)
    m = await _create_funded_community_market(client, h, title="Neg Inventory Exploit")
    market_id = m["market_id"]
    yes_tok = m["tokens"][0]["token_id"]

    # Mint 50 YES + 50 NO via CTF split (AMM q_yes is still 0)
    r_split = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market_id, "shares": "50"},
        headers=h,
    )
    assert r_split.status_code == 200, r_split.text

    # Attempt to SELL 50 YES into AMM with q_yes == 0 -> must be rejected (409)
    r_sell = await client.post(
        f"/api/v4/prediction/amm/{market_id}/trade",
        json={"token_id": yes_tok, "side": "SELL", "shares": 50},
        headers=h,
    )
    assert r_sell.status_code == 409, r_sell.text

    # Verify q_yes stayed non-negative
    pool = (await client.get(f"/api/v4/prediction/amm/{market_id}")).json()
    assert pool["q_yes"] >= 0.0


# ---------------------------------------------------------------------------
# Finding #4 (CRITICAL): Kalshi Verifier in /propose & Rule 3 in Worker
# ---------------------------------------------------------------------------
async def test_vuln4_propose_enforces_kalshi_whitelist_and_worker_applies_rule3(client, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    adm = await _admin_headers(client)
    u = await auth_headers(client, "vuln4_creator@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=u)

    kalshi_rules = (
        "Resolves Yes if Take-Two Interactive publicly reports that GTA VI reached at least 36 million units sold-in.\n"
        "Outcome verified from Reuters and Take-Two Interactive.\n"
        "If there is no data published by a Source Agency by the Expiration Date, all markets will resolve to No."
    )
    m1 = await _create_funded_community_market(
        client, u, title="GTA VI Whitelist Check", resolution_criteria=kalshi_rules
    )
    # Close m1 so /propose can run
    async with AsyncSessionLocal() as session:
        mkt = (await session.execute(select(Market).where(Market.id == m1["market_id"]))).scalar_one()
        mkt.status = "CLOSED"
        await session.commit()

    # Non-whitelisted domain passed to /resolution/propose MUST be rejected (422)
    r_bad = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={
            "market_id": m1["market_id"],
            "proposed_outcome_index": 0,
            "source_url": "https://fake-rumor-blog.example/gta6",
            "evidence_text": "Take-Two Interactive reported 42 million units sold-in.",
        },
        headers=adm,
    )
    assert r_bad.status_code == 422, r_bad.text

    # Whitelisted domain succeeds (200)
    r_ok = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={
            "market_id": m1["market_id"],
            "proposed_outcome_index": 0,
            "source_url": "https://www.reuters.com/technology/gta6",
            "evidence_text": "Take-Two Interactive publicly reported GTA VI sold-in 42 million units.",
        },
        headers=adm,
    )
    assert r_ok.status_code == 200, r_ok.text

    # Kalshi Rule 3: expired qualitative market with no proposal auto-proposes NO in worker tick
    m2 = await _create_funded_community_market(
        client, u, title="GTA VI No Data Default", resolution_criteria=kalshi_rules
    )
    async with AsyncSessionLocal() as session:
        ev2 = (await session.execute(select(Event).where(Event.id == m2["event_id"]))).scalar_one()
        ev2.end_date = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    async with AsyncSessionLocal() as session:
        tick = await run_resolution_tick(session)
        await session.commit()
        assert tick["closed"] >= 1
        assert tick["proposed"] >= 1

        mkt2 = (await session.execute(select(Market).where(Market.id == m2["market_id"]))).scalar_one()
        assert mkt2.status == "IN_RESOLUTION"


# ---------------------------------------------------------------------------
# Finding #5 & #9 (HIGH / MEDIUM): PATCH Oracle Validation Bypass & end_date
# ---------------------------------------------------------------------------
async def test_vuln5_patch_community_market_validates_oracle_fields(client):
    h = await auth_headers(client, "vuln5_creator@example.com")
    r_create = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Patch Validation Market",
            "question": "Will BTC hit 200k?",
            "category": "Crypto",
            "resolution_criteria": "Resolves Yes if BTC >= 200000.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 0,
        },
        headers=h,
    )
    assert r_create.status_code == 201, r_create.text
    mid = r_create.json()["market_id"]

    # Invalid comparator rejected (422)
    r_bad_cmp = await client.patch(
        f"/api/v4/prediction/community/markets/{mid}",
        json={"oracle_comparator": "DROP"},
        headers=h,
    )
    assert r_bad_cmp.status_code == 422

    # Feed without threshold rejected (422)
    r_no_thr = await client.patch(
        f"/api/v4/prediction/community/markets/{mid}",
        json={"oracle_feed": "coingecko:bitcoin"},
        headers=h,
    )
    assert r_no_thr.status_code == 422

    # Threshold without feed rejected (422)
    r_no_feed = await client.patch(
        f"/api/v4/prediction/community/markets/{mid}",
        json={"oracle_threshold": 200000},
        headers=h,
    )
    assert r_no_feed.status_code == 422

    # Paired feed + threshold + valid comparator succeeds (200)
    r_good = await client.patch(
        f"/api/v4/prediction/community/markets/{mid}",
        json={"oracle_feed": "coingecko:bitcoin", "oracle_threshold": 200000, "oracle_comparator": ">="},
        headers=h,
    )
    assert r_good.status_code == 200, r_good.text


# ---------------------------------------------------------------------------
# Finding #6 (HIGH): Dispute Counter-Bond Minimum (100 AGX)
# ---------------------------------------------------------------------------
async def test_vuln6_dispute_enforces_100_agx_minimum_bond(client):
    adm = await _admin_headers(client)
    u = await auth_headers(client, "vuln6_disputer@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 500}, headers=u)

    m = await _create_funded_community_market(client, u, title="Dispute Bond Floor")
    async with AsyncSessionLocal() as session:
        mkt = (await session.execute(select(Market).where(Market.id == m["market_id"]))).scalar_one()
        mkt.status = "CLOSED"
        await session.commit()

    r_prop = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": m["market_id"], "proposed_outcome_index": 0},
        headers=adm,
    )
    assert r_prop.status_code == 200, r_prop.text

    # Passing 50 AGX (old PROPOSAL_BOND) MUST be rejected with 400 (< 100 AGX minimum)
    r_under = await client.post(
        "/api/v4/prediction/resolution/dispute",
        json={"market_id": m["market_id"], "counter_bond": 50},
        headers=u,
    )
    assert r_under.status_code == 400, r_under.text


# ---------------------------------------------------------------------------
# Finding #7 (HIGH): OOM Protection & Content-Type Cap in fetch_source_text
# ---------------------------------------------------------------------------
async def test_vuln7_fetch_source_text_caps_bytes_and_rejects_binary(monkeypatch):
    class _FakeStreamResp:
        def __init__(self, ctype: str, chunks: list[bytes]):
            self.status_code = 200
            self.headers = {"content-type": ctype}
            self._chunks = chunks
            self.chunks_read = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            for c in self._chunks:
                self.chunks_read += 1
                yield c

    class _FakeClient:
        resp_obj = None

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, headers=None):
            return self.resp_obj

    monkeypatch.setattr("app.services.oracle_verifier.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr("app.services.oracle_verifier._validate_public_http_url", lambda u: u)

    # 1. Binary Content-Type rejected (422)
    _FakeClient.resp_obj = _FakeStreamResp("application/octet-stream", [b"\x00\x01\x02"])
    with pytest.raises(HTTPException) as exc:
        await fetch_source_text("https://reuters.com/file.bin")
    assert exc.value.status_code == 422

    # 2. Huge 200 KB text stream stops reading after 64 KB cap
    big_chunks = [b"A" * 16384 for _ in range(15)]  # 240 KB total
    resp = _FakeStreamResp("text/html; charset=utf-8", big_chunks)
    _FakeClient.resp_obj = resp
    text = await fetch_source_text("https://reuters.com/article", max_chars=4000, max_bytes=65536)
    assert len(text) == 4000
    assert resp.chunks_read <= 4  # Stopped at 64 KB (4 x 16 KB), never read all 15 chunks!


# ---------------------------------------------------------------------------
# Finding #8 (HIGH): Unfunded Community Market Spam Cap (429)
# ---------------------------------------------------------------------------
async def test_vuln8_unfunded_community_market_spam_capped(client):
    h = await auth_headers(client, "vuln8_spammer@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=h)

    for i in range(5):
        r = await client.post(
            "/api/v4/prediction/community/markets",
            json={
                "title": f"Spam Market {i}",
                "question": f"Will spam market {i} pass?",
                "category": "Crypto",
                "resolution_criteria": "Resolves Yes if official source confirms.",
                "end_date": "2027-06-01T00:00:00Z",
                "initial_liquidity_usdc": 0,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text

    # 6th unfunded market is rate-limited (429)
    r6 = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Spam Market 6",
            "question": "Will spam market 6 pass?",
            "category": "Crypto",
            "resolution_criteria": "Resolves Yes if official source confirms.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 0,
        },
        headers=h,
    )
    assert r6.status_code == 429, r6.text

    # Funded market (>= $10) bypasses unfunded cap and succeeds (201)
    r_funded = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Funded Market OK",
            "question": "Will funded market pass?",
            "category": "Crypto",
            "resolution_criteria": "Resolves Yes if official source confirms.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 20,
        },
        headers=h,
    )
    assert r_funded.status_code == 201, r_funded.text


# ---------------------------------------------------------------------------
# Finding #11 (MEDIUM): merge_positions Blocked on EXPIRED Market
# ---------------------------------------------------------------------------
async def test_vuln11_merge_positions_rejected_on_expired_market(client):
    h = await auth_headers(client, "vuln11_user@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 200}, headers=h)
    m = await _create_funded_community_market(client, h, title="Merge Expired Test")

    async with AsyncSessionLocal() as session:
        mkt = (await session.execute(select(Market).where(Market.id == m["market_id"]))).scalar_one()
        mkt.status = "EXPIRED"
        await session.commit()

    r_merge = await client.post(
        "/api/v4/prediction/positions/merge",
        json={"market_id": m["market_id"], "shares": "5"},
        headers=h,
    )
    assert r_merge.status_code == 409, r_merge.text
