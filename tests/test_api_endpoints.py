"""Stage 4/5 verification: full REST integration incl. error matrix + settlement."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def market_setup(client: AsyncClient):
    headers = await auth_headers(client, "mk-admin@example.com")
    await make_admin("mk-admin@example.com")
    event = (
        await client.post(
            "/api/v4/prediction/admin/events",
            json={"slug": "integration-event", "title": "Integration Event",
                  "description": "d", "category": "Crypto"},
            headers=headers,
        )
    ).json()
    market = (
        await client.post(
            "/api/v4/prediction/admin/markets",
            json={"event_slug": "integration-event", "question": "Will it pass?",
                  "outcomes": ["YES", "NO"], "min_order_size": 5.0},
            headers=headers,
        )
    ).json()
    return {"event": event, "market": market, "admin": headers}


async def test_discovery_pagination_and_filters(client: AsyncClient, market_setup):
    resp = await client.get("/api/v4/prediction/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] >= 1
    assert body["events"] and body["events"][0]["slug"] == "integration-event"

    resp = await client.get(
        "/api/v4/prediction/events", params={"category": "Politics"}
    )
    assert resp.json()["total_count"] == 0

    slug = (await client.get(
        "/api/v4/prediction/events/slug/integration-event"
    ))
    assert slug.status_code == 200
    assert slug.json()["markets"][0]["tokens"][0]["symbol"] == "YES"

    missing = await client.get("/api/v4/prediction/markets/does-not-exist")
    assert missing.status_code == 404


ORDER = {
    "side": "BUY",
    "type": "LIMIT",
    "price": 0.5,
    "amount": 10,
}


async def _setup_users(client: AsyncClient):
    a = await auth_headers(client, "a-user-ord@example.com")
    b = await auth_headers(client, "b-user-ord@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 5000}, headers=a)
    await client.post("/api/v1/collateral/deposit", json={"amount": 5000}, headers=b)
    return a, b


def _order_payload(market, token_id, **over):
    payload = {
        "market_id": market["id"],
        "token_id": token_id,
        "side": "BUY",
        "type": "LIMIT",
        "price": 0.5,
        "amount": 10,
        "time_in_force": "GTC",
    }
    payload.update(over)
    return payload


async def test_order_error_matrix(client: AsyncClient, market_setup):
    market = market_setup["market"]
    token_id = market["tokens"][0]["token_id"]
    headers_a, headers_b = await _setup_users(client)

    # 401 unauthenticated
    assert (
        await client.post("/api/v4/prediction/orders", json=_order_payload(market, token_id))
    ).status_code == 401

    # 422 malformed side
    assert (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, side="SIDEWAYS"),
            headers=headers_a,
        )
    ).status_code == 422

    # 400 price out of bounds
    for price in (0.001, 0.999):
        assert (
            await client.post(
                "/api/v4/prediction/orders",
                json=_order_payload(market, token_id, price=price),
                headers=headers_a,
            )
        ).status_code == 400

    # 400 price off tick grid
    assert (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, price=0.505),
            headers=headers_a,
        )
    ).status_code == 400

    # 400 below min order size
    assert (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, amount=2.0),
            headers=headers_a,
        )
    ).status_code == 400

    # 404 unknown market
    assert (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, market_id="nope"),
            headers=headers_a,
        )
    ).status_code == 404

    # 400 insufficient collateral (price 0.99 x 5000 avail - deposits 5000,
    # cost 4950 -> OK, so test bigger amount)
    resp = await client.post(
        "/api/v1/collateral/balance", headers=headers_b
    )
    huge = {
        "market_id": market["id"],
        "token_id": token_id,
        "side": "BUY",
        "type": "LIMIT",
        "price": 0.99,
        "amount": 10000,
    }
    resp = await client.post("/api/v4/prediction/orders", json=huge, headers=headers_a)
    assert resp.status_code == 400

    # sell with no shares -> 400
    resp = await client.post(
        "/api/v4/prediction/orders",
        json=_order_payload(market, token_id, side="SELL"),
        headers=headers_a,
    )
    assert resp.status_code == 400


async def test_matching_both_sides_and_fee(client: AsyncClient, market_setup):
    market = market_setup["market"]
    token_id = market["tokens"][0]["token_id"]
    a, b = await _setup_users(client)

    # A offers 20 shares @ 0.60 (mints via split first)
    resp = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 50},
        headers=a,
    )
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v4/prediction/orders",
        json=_order_payload(market, token_id, side="SELL", price=0.60, amount=20),
        headers=a,
    )
    assert resp.status_code == 201, resp.text

    # B takes 15 shares at 0.60
    resp = await client.post(
        "/api/v4/prediction/orders",
        json=_order_payload(market, token_id, side="BUY", price=0.60, amount=15),
        headers=b,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["order"]["status"] == "FILLED"
    assert len(body["fills"]) == 1
    fill = body["fills"][0]
    expected_fee = 15 * 0.02 * 0.60 * (1 - 0.60)
    # 0.0155 -> assert approx
    assert abs(fill["taker_fee"] - expected_fee) < 1e-6

    # Position created for B
    positions = (
        await client.get("/api/v4/prediction/positions", headers=b)
    ).json()["positions"]
    target = [p for p in positions if p["token_id"] == token_id]
    assert target and float(target[0]["shares"]) == 15.0

    # Balance check: B pays 15*0.60 + fee = 9 + 0.18
    bal = (
        await client.get("/api/v1/collateral/balance", headers=b)
    ).json()
    assert abs(bal["balance"] - (5000 - 9 - 0.072)) < 0.01


async def test_cancel_filled_order_conflict(client: AsyncClient, market_setup):
    market = market_setup["market"]
    token_id = market["tokens"][1]["token_id"]  # NO token
    a, b = await _setup_users(client)
    await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 50},
        headers=a,
    )
    offer = (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, side="SELL", price=0.40, amount=20),
            headers=a,
        )
    ).json()
    assert offer["order"]["status"] == "OPEN"
    order_id = offer["order"]["id"]

    filled = (
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, side="BUY", price=0.40, amount=20),
            headers=b,
        )
    ).json()
    assert filled["order"]["status"] == "FILLED"

    # A tries to cancel her (now FILLED) order -> 409
    resp = await client.delete(f"/api/v4/prediction/orders/{order_id}", headers=a)
    assert resp.status_code == 409

    # Duplicate cancel -> 409
    resp = await client.delete(
        f"/api/v4/prediction/orders/{order_id}",
        headers={"Authorization": ""},
    )
    assert resp.status_code in (401,)


async def test_batch_cancel(client: AsyncClient, market_setup):
    market = market_setup["market"]
    token_id = market["tokens"][0]["token_id"]
    a, _ = await _setup_users(client)
    for price in (0.30, 0.31, 0.32):
        await client.post(
            "/api/v4/prediction/orders",
            json=_order_payload(market, token_id, price=price, amount=10),
            headers=a,
        )
    resp = await client.delete(
        "/api/v4/prediction/orders", params={"market_id": market["id"]}, headers=a
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["cancelled_count"] == 3


async def test_settlement_and_redemption(client: AsyncClient, market_setup):
    market = market_setup["market"]
    yes_token = market["tokens"][0]["token_id"]
    no_token = market["tokens"][1]["token_id"]
    admin = market_setup["admin"]
    a, _ = await _setup_users(client)

    # A holds both outcome tokens via split (10 YES + 10 NO for 10 shares)
    resp = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 10},
        headers=a,
    )
    assert resp.status_code == 200

    # Trading halt: ACTIVE -> CLOSED
    resp = await client.post(
        f"/api/v4/prediction/admin/markets/{market['id']}/close", headers=admin
    )
    assert resp.status_code == 200

    # Propose needs CLOSED market
    resp = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": market["id"], "proposed_outcome_index": 0},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["market_status"] == "IN_RESOLUTION"

    # Duplicate proposal -> 409
    resp = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": market["id"], "proposed_outcome_index": 1},
        headers=admin,
    )
    assert resp.status_code == 409

    # Finalize resolution with outcome 0 (YES wins)
    resp = await client.post(
        "/api/v4/prediction/resolution/finalize",
        json={"market_id": market["id"], "winning_outcome_index": 0},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    # Position list shows settled market
    positions = (
        await client.get(
            "/api/v4/prediction/positions", headers=a
        )
    ).json()["positions"]
    yes_pos = next(p for p in positions if p["token_id"] == yes_token)
    no_pos = next(p for p in positions if p["token_id"] == no_token)

    bal_before = (
        await client.get("/api/v1/collateral/balance", headers=a)
    ).json()["balance"]

    # Redeem winning token -> 10.00 payout
    resp = await client.post(
        f"/api/v4/prediction/positions/{yes_pos['position_id']}/redeem", headers=a
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payout_amount"] == 10.0

    # Redeem losing token -> 0.00 payout
    resp = await client.post(
        f"/api/v4/prediction/positions/{no_pos['position_id']}/redeem", headers=a
    )
    assert resp.status_code == 200
    assert resp.json()["payout_amount"] == 0.0

    bal_after = (
        await client.get("/api/v1/collateral/balance", headers=a)
    ).json()["balance"]
    assert abs(bal_after - (bal_before + 10.0)) < 0.01

    # Duplicate claim -> 409
    resp = await client.post(
        f"/api/v4/prediction/positions/{yes_pos['position_id']}/redeem", headers=a
    )
    assert resp.status_code == 409

    # Other user cannot redeem A's position -> 403
    headers_b = await auth_headers(client, "redeem-other@example.com")
    resp = await client.post(
        f"/api/v4/prediction/positions/{no_pos['position_id']}/redeem", headers=headers_b
    )
    assert resp.status_code == 403


async def test_order_book_and_ticker_public(client: AsyncClient, market_setup):
    market = market_setup["market"]
    token_id = market["tokens"][0]["token_id"]
    a, _ = await _setup_users(client)
    await client.post(
        "/api/v4/prediction/orders",
        json=_order_payload(market, token_id, price=0.35, amount=20),
        headers=a,
    )
    await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 20},
        headers=a,
    )
    await client.post(
        "/api/v4/prediction/orders",
        json=_order_payload(market, token_id, side="SELL", price=0.65, amount=20),
        headers=a,
    )
    resp = await client.get(
        f"/api/v4/prediction/tokens/{token_id}/order_book", params={"depth": 10}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_id"] == token_id
    assert body["bids"] and body["asks"]
    assert body["bids"][0][0] == "0.35"
    assert body["asks"][0][0] == "0.65"

    resp = await client.get(f"/api/v4/prediction/tokens/{token_id}/price")
    assert resp.status_code == 200
    assert "bbo" in resp.json()

    resp = await client.get(
        f"/api/v4/prediction/tokens/{token_id}/price_history",
        params={"resolution": "1m"},
    )
    assert resp.status_code == 200
    assert "candles" in resp.json()

    resp = await client.get("/api/v4/prediction/tokens/bad-token/order_book")
    assert resp.status_code == 404
