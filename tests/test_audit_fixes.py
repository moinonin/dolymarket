"""Tests for GPT_AUDIT.md P0/P1 safety fixes."""
import time
import pytest
from httpx import AsyncClient

from app.core.security import compute_hmac_signature, split_api_key
from app.main import AUTH_ATTACK_PATHS
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def test_stp_blocks_second_level_and_fee_insufficient_rejected(client: AsyncClient):
    ah = await auth_headers(client, "audit_adm@example.com")
    await make_admin("audit_adm@example.com")
    uh_a = await auth_headers(client, "audit_a@example.com")
    uh_b = await auth_headers(client, "audit_b@example.com")
    uh_c = await auth_headers(client, "audit_c@example.com")

    await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=ah)
    await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=uh_a)
    await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=uh_b)
    # Exact notional $2.50 with zero fee headroom
    await client.post("/api/v1/collateral/deposit", json={"amount": 2.50}, headers=uh_c)

    mk = (
        await client.post(
            "/api/v4/prediction/community/markets",
            json={
                "title": "Audit STP Fee Market",
                "question": "Audit test?",
                "category": "Crypto",
                "outcomes": ["YES", "NO"],
                "resolution_criteria": "Resolves YES per test.",
                "initial_liquidity_usdc": 50,
            },
            headers=ah,
        )
    ).json()
    mid, yes_tok = mk["market_id"], mk["tokens"][0]["token_id"]

    await client.post(f"/api/v4/prediction/amm/{mid}/trade", json={"token_id": yes_tok, "side": "BUY", "shares": 10}, headers=uh_b)
    await client.post(f"/api/v4/prediction/amm/{mid}/trade", json={"token_id": yes_tok, "side": "BUY", "shares": 5}, headers=uh_a)

    # B rests 5 @ 0.50, then A rests 5 @ 0.50 behind B
    await client.post("/api/v4/prediction/orders", json={"market_id": mid, "token_id": yes_tok, "side": "SELL", "type": "LIMIT", "price": 0.50, "amount": 5}, headers=uh_b)
    await client.post("/api/v4/prediction/orders", json={"market_id": mid, "token_id": yes_tok, "side": "SELL", "type": "LIMIT", "price": 0.50, "amount": 5}, headers=uh_a)

    # A buys 10 @ 0.50 -> fills B's 5, stops before A's own resting 5
    r_stp = await client.post("/api/v4/prediction/orders", json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.50, "amount": 10}, headers=uh_a)
    assert r_stp.status_code == 201
    assert len(r_stp.json()["fills"]) == 1
    assert r_stp.json()["order"]["filled_amount"] == 5.0

    # B rests 5 @ 0.50; C tries to buy 5 @ 0.50 with exact $2.50 -> rejected (insufficient for fee)
    await client.post("/api/v4/prediction/orders", json={"market_id": mid, "token_id": yes_tok, "side": "SELL", "type": "LIMIT", "price": 0.50, "amount": 5}, headers=uh_b)
    r_fee = await client.post("/api/v4/prediction/orders", json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.50, "amount": 5}, headers=uh_c)
    assert r_fee.status_code == 400
    assert "fee" in r_fee.json()["detail"].lower()


async def test_wallet_auth_in_rate_limit_and_hmac_replay_blocked(client: AsyncClient):
    assert "/api/v1/auth/wallet/challenge" in AUTH_ATTACK_PATHS
    assert "/api/v1/auth/wallet/verify" in AUTH_ATTACK_PATHS

    # Register & generate API key
    reg = await client.post("/api/v1/auth/register", json={"email": "hmac_replay@example.com", "password": "hunter2secret"})
    tok = reg.json()["access_token"]
    key_res = await client.post("/api/v1/auth/api-key", headers={"Authorization": f"Bearer {tok}"})
    api_key = key_res.json()["api_key"]

    ts = str(int(time.time()))
    body = b'{"amount":10}'
    secret = split_api_key(api_key)
    assert secret is not None
    sig = compute_hmac_signature(secret, ts, "POST", "/api/v1/collateral/deposit", body)
    headers = {
        "X-API-KEY": api_key,
        "X-TIMESTAMP": ts,
        "X-SIGNATURE": sig,
        "Content-Type": "application/json",
    }
    r1 = await client.post("/api/v1/collateral/deposit", content=body, headers=headers)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/collateral/deposit", content=body, headers=headers)
    assert r2.status_code == 401
    assert "Replayed HMAC" in r2.json()["detail"]


async def test_post_commit_callback_skipped_on_rollback_and_siwe_ignores_client_domain(client: AsyncClient):
    from app.db.session import AsyncSessionLocal, queue_post_commit

    fired: list[str] = []
    async with AsyncSessionLocal() as s:
        async def _cb():
            fired.append("ran")
        queue_post_commit(s, _cb)
        await s.rollback()
    assert fired == []

    # SIWE challenge must not accept arbitrary client-supplied phishing domain
    r_ch = await client.post(
        "/api/v1/auth/wallet/challenge",
        json={
            "address": "0x1111111111111111111111111111111111111111",
            "domain": "evil-phishing.example",
            "uri": "https://evil-phishing.example",
        },
    )
    assert r_ch.status_code == 200
    assert "evil-phishing.example" not in r_ch.json()["challenge"]
