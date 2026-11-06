"""Regression tests for the production-architecture improvements."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import security
from app.core.ratelimit import TokenBucketLimiter
from app.db.session import AsyncSessionLocal
from app.engine.clob import MatchingEngine, OrderBook
from app.models.domain import Event, Market, OutcomeToken, TradeFill, User
from app.services import collateral
from app.services.settlement import split_position
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


def _token_bucket_burst_and_refill_sync():
    limiter = TokenBucketLimiter()
    assert limiter.allow("client", rate=1.0, capacity=2.0)[0] is True
    assert limiter.allow("client", rate=1.0, capacity=2.0)[0] is True
    allowed, retry_after = limiter.allow("client", rate=1.0, capacity=2.0)
    assert allowed is False
    assert retry_after > 0


async def test_token_bucket_burst_and_refill():
    _token_bucket_burst_and_refill_sync()


async def _market(session, slug: str):
    event = Event(slug=slug, title="t", category="Crypto")
    session.add(event)
    await session.flush()
    market = Market(
        event_id=event.id,
        condition_id=f"cond-{slug}",
        question="q",
        outcomes=["YES", "NO"],
        tick_size=Decimal("0.01"),
        min_order_size=Decimal(5),
    )
    session.add(market)
    await session.flush()
    token = OutcomeToken(
        token_id=f"tok-{slug}",
        market_id=market.id,
        outcome_index=0,
        symbol="YES",
    )
    session.add(token)
    await session.flush()
    return market, token


async def test_in_memory_book_is_shared_and_sequenced():
    async with AsyncSessionLocal() as session:
        user = User(email="seq-maker@e.com", hashed_password="x" * 60)
        session.add(user)
        await session.flush()
        await collateral.deposit(session, user, Decimal(1000))
        market, token = await _market(session, "seq-event")

        first = MatchingEngine()
        order = await first.submit_order(
            session,
            user.id,
            market,
            token,
            collateral,
            side="BUY",
            price=Decimal("0.35"),
            amount=Decimal(10),
        )

        # A brand-new engine instance sees the same process-wide book without
        # re-querying resting orders from SQL.
        second = MatchingEngine()
        resting = await OrderBook(session, token.token_id).resting_orders("BUY")
        assert [o.id for o in resting] == [order.id]
        live_book = await second.order_books.get(session, token.token_id)
        snapshot = live_book.snapshot()
        assert snapshot["bids"][0][0] == "0.35"
        assert snapshot["sequence"] > 0

        # Fill path assigns a deterministic, monotonically increasing seq.
        seller = User(email="seq-seller@e.com", hashed_password="x" * 60)
        session.add(seller)
        await session.flush()
        await collateral.deposit(session, seller, Decimal(1000))
        await split_position(session, seller, market, Decimal(20))
        await second.submit_order(
            session,
            seller.id,
            market,
            token,
            collateral,
            side="SELL",
            price=Decimal("0.35"),
            amount=Decimal(10),
        )

        fills = (await session.execute(select(TradeFill))).scalars().all()
        assert fills
        assert fills[0].sequence_id is not None
        assert fills[0].sequence_id > 0
        await session.rollback()


async def test_idempotency_key_replays_and_conflicts(client: AsyncClient):
    admin = await auth_headers(client, "idem-admin@example.com")
    await make_admin("idem-admin@example.com")
    await client.post(
        "/api/v4/prediction/admin/events",
        json={"slug": "idem-event", "title": "Idempotency", "category": "Crypto"},
        headers=admin,
    )
    market = (
        await client.post(
            "/api/v4/prediction/admin/markets",
            json={
                "event_slug": "idem-event",
                "question": "Will retry dedupe?",
                "outcomes": ["YES", "NO"],
            },
            headers=admin,
        )
    ).json()
    trader = await auth_headers(client, "idem-trader@example.com")
    await client.post(
        "/api/v1/collateral/deposit", json={"amount": 1000}, headers=trader
    )

    payload = {
        "market_id": market["id"],
        "token_id": market["tokens"][0]["token_id"],
        "side": "BUY",
        "type": "LIMIT",
        "price": 0.42,
        "amount": 10,
        "time_in_force": "GTC",
    }
    headers = {**trader, "X-Idempotency-Key": "retry-1"}

    first = await client.post("/api/v4/prediction/orders", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v4/prediction/orders", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert first.json()["order"]["id"] == second.json()["order"]["id"]

    orders = (await client.get("/api/v4/prediction/orders", headers=trader)).json()[
        "orders"
    ]
    assert len(orders) == 1

    conflict = await client.post(
        "/api/v4/prediction/orders",
        json={**payload, "amount": 20},
        headers=headers,
    )
    assert conflict.status_code == 409


async def test_hmac_api_key_authentication(client: AsyncClient):
    headers = await auth_headers(client, "hmac-trader@example.com")
    issued = (
        await client.post("/api/v1/auth/api-key", headers=headers)
    ).json()
    api_key = issued["api_key"]
    secret = security.split_api_key(api_key)
    timestamp = str(int(__import__("time").time()))
    path = "/api/v1/collateral/balance"
    signature = security.compute_hmac_signature(
        secret, timestamp, "GET", path, b""
    )

    resp = await client.get(
        path,
        headers={
            "X-API-KEY": api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
        },
    )
    assert resp.status_code == 200, resp.text

    bad = await client.get(
        path,
        headers={
            "X-API-KEY": api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": "0" * 64,
        },
    )
    assert bad.status_code == 401

    # A stale timestamp is rejected even when the signature is correct.
    stale_timestamp = str(int(__import__("time").time()) - 3600)
    stale_signature = security.compute_hmac_signature(
        secret, stale_timestamp, "GET", path, b""
    )
    stale = await client.get(
        path,
        headers={
            "X-API-KEY": api_key,
            "X-TIMESTAMP": stale_timestamp,
            "X-SIGNATURE": stale_signature,
        },
    )
    assert stale.status_code == 401


async def test_in_memory_book_is_rehydrated_after_rollback():
    async with AsyncSessionLocal() as session:
        user = User(email="rollback-maker@e.com", hashed_password="x" * 60)
        session.add(user)
        await session.flush()
        await collateral.deposit(session, user, Decimal(1000))
        market, token = await _market(session, "rollback-event")

        engine = MatchingEngine()
        await engine.submit_order(
            session,
            user.id,
            market,
            token,
            collateral,
            side="BUY",
            price=Decimal("0.30"),
            amount=Decimal(10),
        )
        book = await engine.order_books.get(session, token.token_id)
        assert len(book.resting_orders("BUY")) == 1

        # The transaction rolls back: the cached book must not keep liquidity
        # that was never committed.
        await session.rollback()
        engine.order_books.invalidate(token.token_id)
        rehydrated = await engine.order_books.get(session, token.token_id)
        assert rehydrated.resting_orders("BUY") == []
