"""Stage 2 verification: auth flow, collateral locking, multi-user isolation."""
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


@pytest.fixture
def api(client: AsyncClient):
    return client


async def test_jwt_and_auth(api: AsyncClient):
    # register
    resp = await api.post(
        "/api/v1/auth/register",
        json={"email": "auth-test@example.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["access_token"]

    # duplicate registration rejected
    resp = await api.post(
        "/api/v1/auth/register",
        json={"email": "auth-test@example.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 400

    # login
    resp = await api.post(
        "/api/v1/auth/login",
        json={"email": "auth-test@example.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    # bad credentials -> 401
    resp = await api.post(
        "/api/v1/auth/login",
        json={"email": "auth-test@example.com", "password": "WrongPass123"},
    )
    assert resp.status_code == 401

    # protected endpoint requires auth -> 401
    resp = await api.get("/api/v1/collateral/balance")
    assert resp.status_code == 401

    resp = await api.get(
        "/api/v1/collateral/balance", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["currency"] == "USDC"


async def test_auth_me_returns_the_session_profile(api: AsyncClient):
    headers = await auth_headers(api, "me@example.com")
    resp = await api.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"

    anonymous = await api.get("/api/v1/auth/me")
    assert anonymous.status_code == 401


async def test_collateral_locking(api: AsyncClient):
    headers = await auth_headers(api, "collateral@example.com")
    await api.post("/api/v1/collateral/deposit", json={"amount": 1000.0}, headers=headers)

    bal = (await api.get("/api/v1/collateral/balance", headers=headers)).json()
    assert bal["balance"] == 1000.0

    # negative deposit -> 422 (pydantic gt=0)
    resp = await api.post("/api/v1/collateral/deposit", json={"amount": -5.0}, headers=headers)
    assert resp.status_code == 422

    # withdraw more than available -> 400
    resp = await api.post("/api/v1/collateral/withdraw", json={"amount": 2000.0}, headers=headers)
    assert resp.status_code == 400

    # valid withdrawal
    resp = await api.post("/api/v1/collateral/withdraw", json={"amount": 400.0}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["balance"] == 600.0

    # ledger trail
    ledger = (await api.get("/api/v1/collateral/ledger", headers=headers)).json()
    kinds = [e["kind"] for e in ledger["entries"]]
    for kind in ("DEPOSIT", "WITHDRAWAL"):
        assert kind in kinds


async def test_multi_user_isolation(api: AsyncClient):
    # marketplace: admin creates event + market
    admin = await auth_headers(api, "admin-iso@example.com")
    await make_admin("admin-iso@example.com")
    await api.post(
        "/api/v4/prediction/admin/events",
        json={
            "slug": "iso-event",
            "title": "Isolation Event",
            "category": "Crypto",
        },
        headers=admin,
    )
    market = (
        await api.post(
            "/api/v4/prediction/admin/markets",
            json={
                "event_slug": "iso-event",
                "question": "Isolation Market?",
                "outcomes": ["YES", "NO"],
            },
            headers=admin,
        )
    ).json()
    token_id = market["tokens"][0]["token_id"]

    user_a = await auth_headers(api, "user-a@example.com")
    user_b = await auth_headers(api, "user-b@example.com")

    await api.post("/api/v1/collateral/deposit", json={"amount": 500.0}, headers=user_a)

    # unauthenticated order placement -> 401
    resp = await api.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market["id"],
            "token_id": token_id,
            "side": "BUY",
            "type": "LIMIT",
            "price": 0.5,
            "amount": 10,
        },
    )
    assert resp.status_code == 401

    # user A places an order
    resp = await api.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market["id"],
            "token_id": token_id,
            "side": "BUY",
            "type": "LIMIT",
            "price": 0.5,
            "amount": 10,
        },
        headers=user_a,
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["order"]["id"]

    # user A only sees own orders
    resp = await api.get("/api/v4/prediction/orders", headers=user_b)
    assert resp.json()["orders"] == []

    # user B cannot cancel user A's order -> 403
    resp = await api.delete(f"/api/v4/prediction/orders/{order_id}", headers=user_b)
    assert resp.status_code == 403

    # user A cancels own order -> OK
    resp = await api.delete(
        f"/api/v4/prediction/orders/{order_id}", headers=user_a
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


async def test_wallet_siwe_authentication(api: AsyncClient):
    from eth_account import Account
    from eth_account.messages import encode_defunct

    acct = Account.create()
    wallet_addr = acct.address

    # 1. Request challenge
    resp = await api.post(
        "/api/v1/auth/wallet/challenge",
        json={"address": wallet_addr, "chain_id": 8453},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    challenge = data["challenge"]
    nonce = data["nonce"]
    assert wallet_addr in challenge
    assert nonce in challenge

    # 2. Sign challenge message
    msg = encode_defunct(text=challenge)
    sig = acct.sign_message(msg).signature.hex()

    # 3. Bad signature rejected
    bad_resp = await api.post(
        "/api/v1/auth/wallet/verify",
        json={
            "address": wallet_addr,
            "signature": "0x" + "a" * 130,
            "nonce": nonce,
        },
    )
    assert bad_resp.status_code == 400

    # 4. Valid signature succeeds and returns token
    auth_resp = await api.post(
        "/api/v1/auth/wallet/verify",
        json={
            "address": wallet_addr,
            "signature": sig,
            "nonce": nonce,
        },
    )
    assert auth_resp.status_code == 200, auth_resp.text
    token_data = auth_resp.json()
    assert token_data["access_token"]
    assert token_data["user"]["dexbuilder_wallet"] == wallet_addr.lower()

    # 5. Token works for authenticated calls
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    me_resp = await api.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["dexbuilder_wallet"] == wallet_addr.lower()

    bal_resp = await api.get("/api/v1/collateral/balance", headers=headers)
    assert bal_resp.status_code == 200
    assert bal_resp.json()["balance"] == 0.0
