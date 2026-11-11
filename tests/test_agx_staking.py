"""AGX staking lifecycle: 7-day lock, 3-day cooldown, ledger integrity."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.domain import AgxLedger, AgxStake, AgxUnstakeCooldown, User
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def agx_user(client: AsyncClient, email: str, funded: str = "10000"):
    headers = await auth_headers(client, email)
    await make_admin(email)
    resp = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": funded},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return headers


async def user_id(email: str) -> str:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one()


async def backdate(model, pk: str, field: str, days: int = 10) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(model, pk)
        setattr(row, field, datetime.now(UTC) - timedelta(days=days))
        await session.commit()


async def ledger_sum(uid: str) -> Decimal:
    async with AsyncSessionLocal() as session:
        total = (
            await session.execute(
                select(func.coalesce(func.sum(AgxLedger.amount), 0)).where(
                    AgxLedger.user_id == uid
                )
            )
        ).scalar_one()
    return Decimal(total or 0)


async def test_stake_creates_active_locked_position(client: AsyncClient):
    headers = await agx_user(client, "stake-basic@example.com")

    resp = await client.post(
        "/api/v1/agx/stake", json={"amount": "100"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["stake"]["status"] == "ACTIVE"
    assert body["stake"]["amount"] == "100.000000000000000000"
    assert body["balance"]["staked_balance"] == "100.000000000000000000"
    assert body["balance"]["balance"] == "9900.000000000000000000"
    assert body["balance"]["tier"] == "1"
    assert body["balance"]["tier_name"] == "Bronze"
    assert body["balance"]["discount_rate"] == "0.050000000000000000"

    locked_until = datetime.fromisoformat(body["stake"]["locked_until"])
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    remaining = locked_until - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < remaining < timedelta(days=7, minutes=1)


async def test_unstake_before_lock_rejected(client: AsyncClient):
    headers = await agx_user(client, "stake-locked@example.com")
    stake = (
        await client.post(
            "/api/v1/agx/stake", json={"amount": "100"}, headers=headers
        )
    ).json()["stake"]

    resp = await client.post(
        "/api/v1/agx/unstake", json={"stake_id": stake["id"]}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "AGX_STAKE_LOCKED"

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["staked_balance"] == "100.000000000000000000"


async def test_cooldown_enforced_then_withdrawn(client: AsyncClient):
    headers = await agx_user(client, "stake-cooldown@example.com")
    stake = (
        await client.post(
            "/api/v1/agx/stake", json={"amount": "250"}, headers=headers
        )
    ).json()["stake"]

    await backdate(AgxStake, stake["id"], "locked_until")
    unstaked = await client.post(
        "/api/v1/agx/unstake", json={"stake_id": stake["id"]}, headers=headers
    )
    assert unstaked.status_code == 200, unstaked.text
    cooldown = unstaked.json()["cooldown"]
    assert cooldown["status"] == "PENDING"
    assert unstaked.json()["balance"]["staked_balance"] == "0.000000000000000000"

    early = await client.post(
        "/api/v1/agx/withdraw",
        json={"cooldown_id": cooldown["id"]},
        headers=headers,
    )
    assert early.status_code == 422
    assert early.json()["detail"] == "AGX_COOLDOWN_ACTIVE"

    await backdate(AgxUnstakeCooldown, cooldown["id"], "cooldown_until")
    done = await client.post(
        "/api/v1/agx/withdraw",
        json={"cooldown_id": cooldown["id"]},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    assert done.json()["balance"]["balance"] == "10000.000000000000000000"
    assert done.json()["balance"]["staked_balance"] == "0.000000000000000000"

    uid = await user_id("stake-cooldown@example.com")
    assert await ledger_sum(uid) == Decimal("10000.000000000000000000")

    async with AsyncSessionLocal() as session:
        record = await session.get(AgxStake, stake["id"])
        assert record.status == "WITHDRAWN"
        cooldown_row = await session.get(AgxUnstakeCooldown, cooldown["id"])
        assert cooldown_row.status == "COMPLETED"


async def test_minimum_and_insufficient_balance(client: AsyncClient):
    headers = await agx_user(client, "stake-limits@example.com", funded="50")

    below = await client.post(
        "/api/v1/agx/stake", json={"amount": "0.999"}, headers=headers
    )
    assert below.status_code == 422
    assert below.json()["detail"] == "AGX_STAKE_BELOW_MINIMUM"

    too_much = await client.post(
        "/api/v1/agx/stake", json={"amount": "50.000000000000000001"}, headers=headers
    )
    assert too_much.status_code == 409
    assert too_much.json()["detail"] == "AGX_INSUFFICIENT_BALANCE"

    exact = await client.post(
        "/api/v1/agx/stake", json={"amount": "50"}, headers=headers
    )
    assert exact.status_code == 201, exact.text
    assert exact.json()["balance"]["balance"] == "0.000000000000000000"


async def test_stake_requires_authentication(client: AsyncClient):
    resp = await client.post("/api/v1/agx/stake", json={"amount": "100"})
    assert resp.status_code == 401


async def test_amounts_must_be_decimal_strings(client: AsyncClient):
    headers = await agx_user(client, "stake-format@example.com")

    numeric = await client.post(
        "/api/v1/agx/stake", json={"amount": 100}, headers=headers
    )
    assert numeric.status_code == 422

    garbage = await client.post(
        "/api/v1/agx/stake", json={"amount": "not-a-number"}, headers=headers
    )
    assert garbage.status_code == 422
    assert garbage.json()["detail"] == "AGX_INVALID_AMOUNT"


async def test_unknown_and_foreign_stake_ids(client: AsyncClient):
    owner = await agx_user(client, "stake-owner@example.com")
    intruder = await auth_headers(client, "stake-intruder@example.com")
    stake = (
        await client.post(
            "/api/v1/agx/stake", json={"amount": "10"}, headers=owner
        )
    ).json()["stake"]

    missing = await client.post(
        "/api/v1/agx/unstake",
        json={"stake_id": "00000000-0000-0000-0000-000000000000"},
        headers=owner,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "AGX_STAKE_NOT_FOUND"

    foreign = await client.post(
        "/api/v1/agx/unstake", json={"stake_id": stake["id"]}, headers=intruder
    )
    assert foreign.status_code == 403
    assert foreign.json()["detail"] == "AGX_FORBIDDEN"


async def test_ledger_invariant_after_mixed_mutations(client: AsyncClient):
    headers = await agx_user(client, "stake-ledger@example.com")
    uid = await user_id("stake-ledger@example.com")

    stake = (
        await client.post(
            "/api/v1/agx/stake", json={"amount": "400"}, headers=headers
        )
    ).json()["stake"]
    await backdate(AgxStake, stake["id"], "locked_until")
    cooldown = (
        await client.post(
            "/api/v1/agx/unstake", json={"stake_id": stake["id"]}, headers=headers
        )
    ).json()["cooldown"]
    await backdate(AgxUnstakeCooldown, cooldown["id"], "cooldown_until")
    await client.post(
        "/api/v1/agx/withdraw",
        json={"cooldown_id": cooldown["id"]},
        headers=headers,
    )

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert Decimal(balance["balance"]) == await ledger_sum(uid)

    async with AsyncSessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(AgxLedger)
                    .where(AgxLedger.user_id == uid)
                    .order_by(AgxLedger.created_at)
                )
            )
            .scalars()
            .all()
        )
    running = Decimal(0)
    for row in rows:
        running += Decimal(row.amount)
        assert running == Decimal(row.balance_after)
    assert {row.kind for row in rows} >= {
        "DEPOSIT",
        "STAKE",
        "UNSTAKE_COOLDOWN",
        "WITHDRAW_STAKE",
    }
