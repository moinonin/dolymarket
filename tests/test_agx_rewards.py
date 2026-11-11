"""AGX 24-hour reward epochs: 40/60 split, proportional payouts, idempotency."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.domain import AgxLedger, User
from app.services import agx, collateral
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def agx_user(client: AsyncClient, email: str, funded: str = "5000"):
    headers = await auth_headers(client, email)
    await make_admin(email)
    resp = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": funded},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return headers


async def stake(client: AsyncClient, headers: dict, amount: str) -> None:
    resp = await client.post(
        "/api/v1/agx/stake", json={"amount": amount}, headers=headers
    )
    assert resp.status_code == 201, resp.text


async def ledger_count(uid: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AgxLedger)
                    .where(AgxLedger.user_id == uid)
                )
            ).scalar_one()
        )


async def test_epoch_split_and_proportional_rewards(client: AsyncClient):
    alice = await agx_user(client, "epoch-alice@example.com")
    bob = await agx_user(client, "epoch-bob@example.com")
    await stake(client, alice, "3000")
    await stake(client, bob, "1000")

    resp = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"total_fees_collected": "1000"},
        headers=alice,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    epoch = body["epoch"]

    assert epoch["epoch_number"] == 1
    assert epoch["total_fees_collected"] == "1000.000000000000000000"
    assert epoch["total_staked_supply"] == "4000.000000000000000000"
    assert epoch["creator_share"] == "400.000000000000000000"
    assert epoch["staker_pool"] == "600.000000000000000000"
    assert epoch["reward_per_token"] == "0.150000000000000000"
    assert epoch["distributed"] is True
    assert body["rewarded_stakers"] == 2

    alice_claim = await client.post("/api/v1/agx/claim-rewards", headers=alice)
    assert alice_claim.status_code == 200
    assert alice_claim.json()["claimed"] == "450.000000000000000000"

    bob_claim = await client.post("/api/v1/agx/claim-rewards", headers=bob)
    assert bob_claim.json()["claimed"] == "150.000000000000000000"

    alice_balance = (await client.get("/api/v1/agx/balance", headers=alice)).json()
    bob_balance = (await client.get("/api/v1/agx/balance", headers=bob)).json()
    assert alice_balance["balance"] == "2450.000000000000000000"
    assert bob_balance["balance"] == "4150.000000000000000000"
    assert Decimal(alice_balance["pending_rewards"]) == 0

    history = (
        await client.get("/api/v1/agx/rewards/history", headers=alice)
    ).json()
    assert history["total"] == "450.000000000000000000"
    assert len(history["rewards"]) == 1
    assert history["rewards"][0]["reference_id"] == "epoch:1"

    listed = (await client.get("/api/v1/agx/epochs")).json()["epochs"]
    assert any(e["epoch_number"] == 1 and e["distributed"] for e in listed)


async def test_duplicate_distribution_is_rejected_without_writes(client: AsyncClient):
    alice = await agx_user(client, "epoch-dupe@example.com")
    bob = await agx_user(client, "epoch-dupe-b@example.com")
    await stake(client, alice, "100")
    await stake(client, bob, "100")

    first = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"total_fees_collected": "200"},
        headers=alice,
    )
    assert first.status_code == 200

    uid = (
        await client.get("/api/v1/auth/me", headers=alice)
    ).json()["id"]
    before = await ledger_count(uid)

    repeat = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"epoch_number": first.json()["epoch"]["epoch_number"]},
        headers=alice,
    )
    assert repeat.status_code == 409
    assert repeat.json()["detail"] == "AGX_EPOCH_ALREADY_DISTRIBUTED"
    assert await ledger_count(uid) == before


async def test_zero_stakers_leaves_pool_undistributed(client: AsyncClient):
    admin = await agx_user(client, "epoch-empty@example.com")
    resp = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"total_fees_collected": "100"},
        headers=admin,
    )
    assert resp.status_code == 200
    epoch = resp.json()["epoch"]
    assert epoch["creator_share"] == "40.000000000000000000"
    assert epoch["staker_pool"] == "60.000000000000000000"
    assert epoch["reward_per_token"] == "0.000000000000000000"
    assert resp.json()["rewarded_stakers"] == 0


async def test_recorded_fees_credit_the_creator_share():
    async with AsyncSessionLocal() as session:
        creator = User(email="epoch-creator@example.com", hashed_password="x" * 60)
        session.add(creator)
        await session.flush()

        await agx.record_fee(session, Decimal("10"), creator_user_id=creator.id)
        epoch, rewarded = await agx.distribute_epoch(session)
        await session.commit()

        assert epoch.total_fees_collected == Decimal("10")
        assert epoch.creator_share == Decimal("4")
        assert epoch.staker_pool == Decimal("6")
        assert rewarded == 0

        account = await collateral.get_or_create_account(session, creator.id)
        assert Decimal(account.balance) == Decimal("4")


async def test_distribution_requires_admin(client: AsyncClient):
    regular = await auth_headers(client, "epoch-regular@example.com")
    resp = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"total_fees_collected": "10"},
        headers=regular,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "AGX_FORBIDDEN"


async def test_claim_without_accrual_is_zero(client: AsyncClient):
    headers = await auth_headers(client, "epoch-none@example.com")
    resp = await client.post("/api/v1/agx/claim-rewards", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["claimed"] == "0.000000000000000000"
