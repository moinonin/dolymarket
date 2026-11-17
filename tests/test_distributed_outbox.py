"""Tests for Sprint 7.1: Authoritative partition leases, durable sequences, transactional outbox, and concurrency."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.engine.book import reset_sequence_state
from app.models.domain import OutboxEvent, TokenPartitionState
from app.services import outbox
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def test_durable_sequences_across_restart_and_outbox_relay(client: AsyncClient):
    ah = await auth_headers(client, "outbox_adm@example.com")
    await make_admin("outbox_adm@example.com")
    uh = await auth_headers(client, "outbox_tr@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 200}, headers=ah)
    await client.post("/api/v1/collateral/deposit", json={"amount": 200}, headers=uh)

    mk = (
        await client.post(
            "/api/v4/prediction/community/markets",
            json={
                "title": "Outbox Partition Market",
                "question": "Durable seq?",
                "category": "Crypto",
                "outcomes": ["YES", "NO"],
                "resolution_criteria": "Resolves YES per test.",
                "initial_liquidity_usdc": 50,
            },
            headers=ah,
        )
    ).json()
    mid, yes_tok = mk["market_id"], mk["tokens"][0]["token_id"]

    # Order 1 allocates durable partition sequences and writes outbox_events
    r1 = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.45, "amount": 5},
        headers=uh,
    )
    assert r1.status_code == 201

    async with AsyncSessionLocal() as s:
        p1 = (
            await s.execute(select(TokenPartitionState).where(TokenPartitionState.token_id == yes_tok))
        ).scalar_one()
        seq_after_1 = p1.last_sequence_id
        assert seq_after_1 >= 2

    # Simulate process restart: wipe all in-memory books & sequencers
    reset_sequence_state()

    # Order 2 must continue monotonically from DB durable sequence (never reset to 1)
    r2 = await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.46, "amount": 5},
        headers=uh,
    )
    assert r2.status_code == 201

    async with AsyncSessionLocal() as s:
        p2 = (
            await s.execute(select(TokenPartitionState).where(TokenPartitionState.token_id == yes_tok))
        ).scalar_one()
        assert p2.last_sequence_id > seq_after_1

        # Relay any remaining unpublished outbox events (idempotent on 2nd pass)
        relayed: list[dict] = []

        async def _sink(evs):
            relayed.extend(evs)

        await outbox.relay_pending_outbox(s, _sink)
        await s.commit()
        assert await outbox.relay_pending_outbox(s, _sink) == 0


async def test_partition_leader_fencing_and_concurrent_matching_no_overfill(client: AsyncClient):
    # 1. Partition lease fencing
    async with AsyncSessionLocal() as s:
        assert await outbox.claim_partition_lease(s, "tok-fence", "pod-a", ttl_seconds=30) is True
        assert await outbox.claim_partition_lease(s, "tok-fence", "pod-b", ttl_seconds=30) is False
        # Expire lease manually -> pod-b takes over
        row = (
            await s.execute(select(TokenPartitionState).where(TokenPartitionState.token_id == "tok-fence"))
        ).scalar_one()
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
        assert await outbox.claim_partition_lease(s, "tok-fence", "pod-b", ttl_seconds=30) is True

    # 2. Concurrent BUY takers competing for a single resting SELL 5 @ 0.50 -> total filled == 5.0
    ah = await auth_headers(client, "conc_adm@example.com")
    await make_admin("conc_adm@example.com")
    maker_h = await auth_headers(client, "conc_maker@example.com")
    t1_h = await auth_headers(client, "conc_t1@example.com")
    t2_h = await auth_headers(client, "conc_t2@example.com")
    for h in (ah, maker_h, t1_h, t2_h):
        await client.post("/api/v1/collateral/deposit", json={"amount": 100}, headers=h)

    mk = (
        await client.post(
            "/api/v4/prediction/community/markets",
            json={
                "title": "Concurrency Market",
                "question": "No overfill?",
                "category": "Crypto",
                "outcomes": ["YES", "NO"],
                "resolution_criteria": "Resolves YES per test.",
                "initial_liquidity_usdc": 50,
            },
            headers=ah,
        )
    ).json()
    mid, yes_tok = mk["market_id"], mk["tokens"][0]["token_id"]

    await client.post(f"/api/v4/prediction/amm/{mid}/trade", json={"token_id": yes_tok, "side": "BUY", "shares": 5}, headers=maker_h)
    await client.post(
        "/api/v4/prediction/orders",
        json={"market_id": mid, "token_id": yes_tok, "side": "SELL", "type": "LIMIT", "price": 0.50, "amount": 5},
        headers=maker_h,
    )

    r1, r2 = await asyncio.gather(
        client.post(
            "/api/v4/prediction/orders",
            json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.50, "amount": 5},
            headers=t1_h,
        ),
        client.post(
            "/api/v4/prediction/orders",
            json={"market_id": mid, "token_id": yes_tok, "side": "BUY", "type": "LIMIT", "price": 0.50, "amount": 5},
            headers=t2_h,
        ),
    )
    assert r1.status_code == 201 and r2.status_code == 201
    total_filled = r1.json()["order"]["filled_amount"] + r2.json()["order"]["filled_amount"]
    assert total_filled == 5.0


async def test_two_independent_engine_registries_enforce_partition_leader_lease(client: AsyncClient):
    from decimal import Decimal
    from app.engine.book import OrderBookRegistry
    from app.engine.clob import MatchingEngine, OrderRejected
    from app.models.domain import Market, OutcomeToken, User
    from app.services import collateral

    ah = await auth_headers(client, "two_pod_adm@example.com")
    await make_admin("two_pod_adm@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 200}, headers=ah)

    mk = (
        await client.post(
            "/api/v4/prediction/community/markets",
            json={
                "title": "Two Pod Lease Market",
                "question": "Single leader?",
                "category": "Crypto",
                "outcomes": ["YES", "NO"],
                "resolution_criteria": "Resolves YES per test.",
                "initial_liquidity_usdc": 50,
            },
            headers=ah,
        )
    ).json()
    mid, yes_tok = mk["market_id"], mk["tokens"][0]["token_id"]

    reg_a = OrderBookRegistry()
    reg_b = OrderBookRegistry()
    eng_a = MatchingEngine(registry=reg_a, leader_id="pod-alpha")
    eng_b = MatchingEngine(registry=reg_b, leader_id="pod-beta")

    async with AsyncSessionLocal() as s:
        u = (await s.execute(select(User).where(User.email == "two_pod_adm@example.com"))).scalar_one()
        m = (await s.execute(select(Market).where(Market.id == mid))).scalar_one()
        t = (await s.execute(select(OutcomeToken).where(OutcomeToken.token_id == yes_tok))).scalar_one()

        o1 = await eng_a.submit_order(
            s, u.id, m, t, collateral, side="BUY", price=Decimal("0.40"), amount=Decimal("5")
        )
        assert o1.status == "OPEN"
        await s.commit()

        with pytest.raises(OrderRejected) as exc_info:
            await eng_b.submit_order(
                s, u.id, m, t, collateral, side="BUY", price=Decimal("0.41"), amount=Decimal("5")
            )
        assert exc_info.value.http_status == 503
