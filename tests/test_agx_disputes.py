"""AGX optimistic-oracle dispute bonds: 100 AGX lock, bonus and slashing."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.domain import AgxDisputeStake, AgxLedger, Event, Market
from app.services import agx
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def agx_user(client: AsyncClient, email: str, funded: str = "1000"):
    headers = await auth_headers(client, email)
    await make_admin(email)
    resp = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": funded},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return headers


async def seed_market(slug: str) -> str:
    async with AsyncSessionLocal() as session:
        event = Event(slug=slug, title="t", category="Crypto")
        session.add(event)
        await session.flush()
        market = Market(
            event_id=event.id,
            condition_id=f"cond-{slug}",
            question="q",
            outcomes=["YES", "NO"],
        )
        session.add(market)
        await session.flush()
        await session.commit()
        return market.id


async def test_default_bond_is_100_agx(client: AsyncClient):
    headers = await agx_user(client, "dispute-default@example.com")
    market_id = await seed_market("dispute-default")

    resp = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": market_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["dispute"]["amount"] == "100.000000000000000000"
    assert body["dispute"]["status"] == "LOCKED"
    assert body["balance"]["balance"] == "900.000000000000000000"
    assert body["balance"]["locked_dispute_balance"] == "100.000000000000000000"


async def test_below_minimum_and_insufficient(client: AsyncClient):
    headers = await agx_user(client, "dispute-limits@example.com", funded="150")
    market_id = await seed_market("dispute-limits")

    below = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": market_id, "amount": "99.999"},
        headers=headers,
    )
    assert below.status_code == 422
    assert below.json()["detail"] == "AGX_DISPUTE_BELOW_MINIMUM"

    too_much = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": market_id, "amount": "150.000000000000000001"},
        headers=headers,
    )
    assert too_much.status_code == 409
    assert too_much.json()["detail"] == "AGX_INSUFFICIENT_BALANCE"


async def test_one_active_bond_per_user_and_market(client: AsyncClient):
    headers = await agx_user(client, "dispute-dupe@example.com")
    market_id = await seed_market("dispute-dupe")

    first = await client.post(
        "/api/v1/agx/dispute-stake", json={"market_id": market_id}, headers=headers
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/agx/dispute-stake", json={"market_id": market_id}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "AGX_DISPUTE_EXISTS"

    other_market = await seed_market("dispute-dupe-2")
    third = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": other_market},
        headers=headers,
    )
    assert third.status_code == 201


async def test_unknown_market_rejected(client: AsyncClient):
    headers = await agx_user(client, "dispute-market@example.com")
    resp = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "AGX_MARKET_NOT_FOUND"


async def test_upheld_dispute_returns_bond_plus_20_percent(client: AsyncClient):
    headers = await agx_user(client, "dispute-upheld@example.com")
    market_id = await seed_market("dispute-upheld")
    bond = (
        await client.post(
            "/api/v1/agx/dispute-stake",
            json={"market_id": market_id},
            headers=headers,
        )
    ).json()["dispute"]

    async with AsyncSessionLocal() as session:
        await agx.resolve_dispute(session, bond["id"], True)
        await session.commit()

    listed = (await client.get("/api/v1/agx/dispute-stakes", headers=headers)).json()
    resolved = next(d for d in listed["disputes"] if d["id"] == bond["id"])
    assert resolved["status"] == "RETURNED"

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["balance"] == "1020.000000000000000000"
    assert balance["locked_dispute_balance"] == "0.000000000000000000"

    async with AsyncSessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(AgxLedger).where(
                        AgxLedger.reference_id == bond["id"],
                        AgxLedger.kind.in_(["DISPUTE_RETURN", "DISPUTE_REWARD"]),
                    )
                )
            )
            .scalars()
            .all()
        )
    amounts = {row.kind: Decimal(row.amount) for row in rows}
    assert amounts["DISPUTE_RETURN"] == Decimal("100")
    assert amounts["DISPUTE_REWARD"] == Decimal("20")


async def test_rejected_dispute_is_slashed_to_treasury(client: AsyncClient):
    headers = await agx_user(client, "dispute-slash@example.com")
    market_id = await seed_market("dispute-slash")
    bond = (
        await client.post(
            "/api/v1/agx/dispute-stake",
            json={"market_id": market_id},
            headers=headers,
        )
    ).json()["dispute"]

    async with AsyncSessionLocal() as session:
        await agx.resolve_dispute(session, bond["id"], False)
        await session.commit()
        stored = await session.get(AgxDisputeStake, bond["id"])
        assert stored.status == "SLASHED"
        assert stored.resolved_at is not None

        slash = (
            await session.execute(
                select(AgxLedger).where(
                    AgxLedger.reference_id.like(f"{bond['id']}:%"),
                    AgxLedger.kind == "SLASH",
                )
            )
        ).scalar_one()
        assert agx.treasury_address() in slash.reference_id

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    # The 100 AGX bond is gone; nothing is returned and no bonus is paid.
    assert balance["balance"] == "900.000000000000000000"
    assert balance["locked_dispute_balance"] == "0.000000000000000000"
    assert balance["pending_rewards"] == "0.000000000000000000"


async def test_bonds_are_scoped_to_the_caller(client: AsyncClient):
    owner = await agx_user(client, "dispute-owner@example.com")
    other = await auth_headers(client, "dispute-other@example.com")
    market_id = await seed_market("dispute-scope")
    await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": market_id},
        headers=owner,
    )

    owner_view = (await client.get("/api/v1/agx/dispute-stakes", headers=owner)).json()
    other_view = (await client.get("/api/v1/agx/dispute-stakes", headers=other)).json()
    assert len(owner_view["disputes"]) == 1
    assert other_view["disputes"] == []

    anonymous = await client.get("/api/v1/agx/dispute-stakes")
    assert anonymous.status_code == 401
