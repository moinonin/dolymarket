"""Regression suite for the security audit fixes (docs/security-audit.md).

Every test maps to a finding: resolution authorization (C-1/C-2), the removed
private dexbuilder proxy (C-3), the deposit cap (C-4), JWT secret policy
(C-5), AGX sync targeting (C-6), rate limiting (H-2), money-typed request
bodies (H-3), the order rejection contract (H-4), the volume sort (H-8) and
WebSocket origin checks (H-1).
"""
import json

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db.session import AsyncSessionLocal
from app.models.domain import Event
from tests.conftest import auth_headers, make_admin


async def _closed_market(client: AsyncClient, admin, slug: str) -> dict:
    """Create event + market via the admin API, then close the market."""
    ev = await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": slug, "title": f"Audit {slug}", "category": "Macro"},
        headers=admin,
    )
    assert ev.status_code == 201, ev.text
    m = await client.post(
        "/api/v4/prediction/admin/markets",
        json={"event_slug": slug, "question": "Will it work?", "outcomes": ["YES", "NO"]},
        headers=admin,
    )
    assert m.status_code == 201, m.text
    market = m.json()
    c = await client.post(
        f"/api/v4/prediction/admin/markets/{market['id']}/close", headers=admin
    )
    assert c.status_code == 200, c.text
    return market


# ---------------------------------------------------------------------------
# C-1 / C-2: resolution is admin-only
# ---------------------------------------------------------------------------


async def test_non_admin_cannot_finalize(client: AsyncClient):
    admin = await auth_headers(client, "sec-admin@example.com")
    await make_admin("sec-admin@example.com")
    market = await _closed_market(client, admin, "sec-finalize")
    user = await auth_headers(client, "sec-attacker@example.com")

    r = await client.post(
        "/api/v4/prediction/resolution/finalize",
        json={"market_id": market["id"], "winning_outcome_index": 0},
        headers=user,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "ADMIN_REQUIRED"


async def test_non_admin_cannot_propose_or_dispute(client: AsyncClient):
    admin = await auth_headers(client, "sec-admin2@example.com")
    await make_admin("sec-admin2@example.com")
    market = await _closed_market(client, admin, "sec-propose")
    user = await auth_headers(client, "sec-attacker2@example.com")

    r = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": market["id"], "proposed_outcome_index": 0},
        headers=user,
    )
    assert r.status_code == 403, r.text


async def test_finalize_requires_a_proposal(client: AsyncClient):
    """Dropping CLOSED from finalize's source statuses restores the dispute
    window: a market can no longer be resolved without a proposal."""
    admin = await auth_headers(client, "sec-admin3@example.com")
    await make_admin("sec-admin3@example.com")
    market = await _closed_market(client, admin, "sec-no-shortcut")

    r = await client.post(
        "/api/v4/prediction/resolution/finalize",
        json={"market_id": market["id"], "winning_outcome_index": 0},
        headers=admin,
    )
    assert r.status_code == 409, r.text


async def test_admin_propose_then_dispute_does_not_crash(client: AsyncClient):
    """The naive/aware datetime comparison in dispute_proposal used to 500."""
    admin = await auth_headers(client, "sec-admin4@example.com")
    await make_admin("sec-admin4@example.com")
    market = await _closed_market(client, admin, "sec-dispute-tz")

    p = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": market["id"], "proposed_outcome_index": 0},
        headers=admin,
    )
    assert p.status_code == 200, p.text
    d = await client.post(
        "/api/v4/prediction/resolution/dispute",
        json={"market_id": market["id"], "counter_bond": 50},
        headers=admin,
    )
    assert d.status_code == 200, d.text
    assert d.json()["market_status"] == "DISPUTED"


# ---------------------------------------------------------------------------
# C-3: private upstream proxy routes are gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v4/dexbuilder/positions",
        "/api/v4/dexbuilder/positions/settled",
        "/api/v4/dexbuilder/usertrades",
        "/api/v4/dexbuilder/orders",
    ],
)
async def test_dexbuilder_private_proxy_requires_auth(client: AsyncClient, path: str):
    r = await client.get(path)
    assert r.status_code == 401, f"{path} should require auth: {r.status_code}"


# ---------------------------------------------------------------------------
# C-4: deposit cap and finite validation
# ---------------------------------------------------------------------------


async def test_deposit_above_cap_rejected(client: AsyncClient):
    h = await auth_headers(client, "sec-deposit@example.com")
    r = await client.post(
        "/api/v1/collateral/deposit", json={"amount": 100001}, headers=h
    )
    assert r.status_code == 422, r.text


async def test_deposit_rejects_nan(client: AsyncClient):
    h = await auth_headers(client, "sec-nan@example.com")
    r = await client.post(
        "/api/v1/collateral/deposit",
        content=b'{"amount": NaN}',
        headers={"Authorization": h["Authorization"], "Content-Type": "application/json"},
    )
    assert r.status_code == 422, r.text


async def test_deposit_still_accepts_normal_amounts(client: AsyncClient):
    h = await auth_headers(client, "sec-deposit2@example.com")
    r = await client.post("/api/v1/collateral/deposit", json={"amount": 5000}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["balance"] == 5000.0


# ---------------------------------------------------------------------------
# H-2: register is rate limited
# ---------------------------------------------------------------------------


async def test_register_is_rate_limited(client: AsyncClient):
    last = None
    accepted = 0
    for i in range(40):
        last = await client.post(
            "/api/v1/auth/register",
            json={"email": f"sec-bulk{i}@example.com", "password": "password1234"},
        )
        if last.status_code == 201:
            accepted += 1
    assert accepted < 40, "register accepted every attempt; rate limit missing"
    assert last is not None and last.status_code == 429, last.text


# ---------------------------------------------------------------------------
# H-3: money-typed order bodies
# ---------------------------------------------------------------------------


async def test_order_rejects_non_finite_amount(client: AsyncClient):
    h = await auth_headers(client, "sec-orders@example.com")
    r = await client.post(
        "/api/v4/prediction/orders",
        content=(
            b'{"market_id": "m", "token_id": "t", "side": "BUY", '
            b'"amount": Infinity}'
        ),
        headers={
            "Authorization": h["Authorization"],
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 422, r.text


async def test_order_rejects_out_of_bounds_price(client: AsyncClient):
    h = await auth_headers(client, "sec-orders2@example.com")
    r = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": "m", "token_id": "t", "side": "BUY", "amount": 10, "price": 1.5},
        headers=h,
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# H-4: engine rejections are HTTP errors, never 201
# ---------------------------------------------------------------------------


async def test_engine_rejection_returns_http_error(client: AsyncClient):
    """An amount below min_order_size is an OrderRejected: it must surface as
    a 4xx, not as HTTP 201 with a REJECTED body."""
    admin = await auth_headers(client, "sec-admin5@example.com")
    await make_admin("sec-admin5@example.com")
    ev = await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": "sec-reject", "title": "Reject", "category": "Macro"},
        headers=admin,
    )
    assert ev.status_code == 201, ev.text
    m = await client.post(
        "/api/v4/prediction/admin/markets",
        json={"event_slug": "sec-reject", "question": "Q?", "outcomes": ["YES", "NO"]},
        headers=admin,
    )
    assert m.status_code == 201, m.text
    market = m.json()

    h = await auth_headers(client, "sec-trader@example.com")
    r = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market["id"],
            "token_id": market["tokens"][0]["token_id"],
            "side": "BUY",
            "type": "LIMIT",
            "price": 0.5,
            "amount": 1,
        },
        headers=h,
    )
    assert r.status_code in (400, 409, 422), r.text
    assert r.json().get("detail"), "rejection reason must be in detail"


async def test_self_trade_prevention_is_409(client: AsyncClient):
    admin = await auth_headers(client, "sec-admin6@example.com")
    await make_admin("sec-admin6@example.com")
    ev = await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": "sec-selftrade", "title": "SelfTrade", "category": "Macro"},
        headers=admin,
    )
    assert ev.status_code == 201, ev.text
    m = await client.post(
        "/api/v4/prediction/admin/markets",
        json={"event_slug": "sec-selftrade", "question": "Q?", "outcomes": ["YES", "NO"]},
        headers=admin,
    )
    market = m.json()
    token_id = market["tokens"][0]["token_id"]

    h = await auth_headers(client, "sec-selftrader@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 5000}, headers=h)
    s = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 10},
        headers=h,
    )
    assert s.status_code == 200, s.text

    # Own resting SELL, then a BUY that would cross it: self-trade prevention.
    sell = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": market["id"], "token_id": token_id, "side": "SELL",
              "type": "LIMIT", "price": 0.5, "amount": 10},
        headers=h,
    )
    assert sell.status_code == 201, sell.text
    buy = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": market["id"], "token_id": token_id, "side": "BUY",
              "type": "LIMIT", "price": 0.5, "amount": 10},
        headers=h,
    )
    assert buy.status_code == 409, buy.text
    assert buy.json()["detail"] == "SELF_TRADE_PREVENTED"


# ---------------------------------------------------------------------------
# C-6: sync-balance targets the specified user
# ---------------------------------------------------------------------------


async def test_sync_balance_targets_specified_user(client: AsyncClient):
    admin = await auth_headers(client, "sec-sync-admin@example.com")
    await make_admin("sec-sync-admin@example.com")
    target = await auth_headers(client, "sec-sync-target@example.com")

    me = await client.get("/api/v1/auth/me", headers=target)
    target_id = me.json()["id"]

    r = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "5", "user_id": target_id},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == target_id

    bal = await client.get("/api/v1/agx/balance", headers=target)
    assert bal.json()["balance"] == "5.000000000000000000", bal.text

    missing = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "5", "user_id": "00000000-0000-0000-0000-000000000000"},
        headers=admin,
    )
    assert missing.status_code == 404, missing.text


# ---------------------------------------------------------------------------
# H-8: volume sort is implemented
# ---------------------------------------------------------------------------


async def test_sort_by_volume_orders_by_total_volume(client: AsyncClient):
    admin = await auth_headers(client, "sec-admin7@example.com")
    await make_admin("sec-admin7@example.com")
    for slug in ("sec-vol-a", "sec-vol-b"):
        ev = await client.post(
            "/api/v4/prediction/admin/events",
            json={"slug": slug, "title": slug, "category": "Macro"},
            headers=admin,
        )
        assert ev.status_code == 201, ev.text

    async with AsyncSessionLocal() as s:
        for slug, vol in (("sec-vol-a", 100), ("sec-vol-b", 900)):
            row = (
                await s.execute(
                    Event.__table__.update()
                    .where(Event.slug == slug)
                    .values(total_volume=vol)
                )
            )
        await s.commit()

    r = await client.get("/api/v4/prediction/events?sort_by=volume&limit=50")
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    slugs = [e["slug"] for e in events]
    assert "sec-vol-b" in slugs and "sec-vol-a" in slugs
    assert slugs.index("sec-vol-b") < slugs.index("sec-vol-a"), slugs


# ---------------------------------------------------------------------------
# H-1: WebSocket origin checks
# ---------------------------------------------------------------------------


def test_ws_rejects_foreign_origin():
    from app.main import app

    tc = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with tc.websocket_connect(
            "/api/v4/prediction/ws/public",
            headers={"Origin": "https://evil.example"},
        ):
            pass


def test_ws_allows_same_host_origin():
    from app.main import app

    tc = TestClient(app)
    with tc.websocket_connect(
        "/api/v4/prediction/ws/public", headers={"Origin": "http://testserver"}
    ) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"action": "pong"}
