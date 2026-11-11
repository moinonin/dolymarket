"""Zero-AGX regression: every USDC trading path works without an AgxBalance row.

AGX is complementary. A user who never touches the token layer must be able to
deposit, mint shares, trade at the unchanged parabolic fee, withdraw collateral
and redeem a settled winning position with no AGX-dependent error anywhere.
"""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.engine.clob import compute_fee, fee_rate_for_category
from app.models.domain import AgxBalance, AgxLedger, TradeFill, User
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def _user_id(email: str) -> str:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one()


async def _agx_rows(email: str) -> tuple[int, int]:
    uid = await _user_id(email)
    async with AsyncSessionLocal() as session:
        balances = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AgxBalance)
                    .where(AgxBalance.user_id == uid)
                )
            ).scalar_one()
        )
        ledger = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AgxLedger)
                    .where(AgxLedger.user_id == uid)
                )
            ).scalar_one()
        )
    return balances, ledger


async def _deposit(client: AsyncClient, headers: dict, amount: float) -> None:
    resp = await client.post(
        "/api/v1/collateral/deposit", json={"amount": amount}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def _balance(client: AsyncClient, headers: dict) -> float:
    resp = await client.get("/api/v1/collateral/balance", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["balance"]


async def test_full_trading_lifecycle_with_zero_agx(client: AsyncClient):
    admin = await auth_headers(client, "zero-admin@example.com")
    await make_admin("zero-admin@example.com")

    event = (
        await client.post(
            "/api/v4/prediction/admin/events",
            json={
                "slug": "zero-token-event",
                "title": "Zero Token Event",
                "description": "no AGX anywhere",
                "category": "Crypto",
            },
            headers=admin,
        )
    )
    assert event.status_code in (200, 201), event.text

    market = (
        await client.post(
            "/api/v4/prediction/admin/markets",
            json={
                "event_slug": "zero-token-event",
                "question": "Will this settle without AGX?",
                "outcomes": ["YES", "NO"],
                "min_order_size": 5.0,
            },
            headers=admin,
        )
    )
    assert market.status_code in (200, 201), market.text
    market = market.json()
    yes_token = market["tokens"][0]["token_id"]

    maker = await auth_headers(client, "zero-maker@example.com")
    taker = await auth_headers(client, "zero-taker@example.com")
    await _deposit(client, maker, 5000)
    await _deposit(client, taker, 5000)

    # Neither participant has ever touched the AGX layer.
    assert await _agx_rows("zero-maker@example.com") == (0, 0)
    assert await _agx_rows("zero-taker@example.com") == (0, 0)

    # Maker mints a complete set, then offers 10 YES at 0.50.
    split = await client.post(
        "/api/v4/prediction/positions/split",
        json={"market_id": market["id"], "shares": 10},
        headers=maker,
    )
    assert split.status_code == 200, split.text

    maker_order = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market["id"],
            "token_id": yes_token,
            "side": "SELL",
            "type": "LIMIT",
            "price": 0.50,
            "amount": 10,
            "time_in_force": "GTC",
        },
        headers=maker,
    )
    assert maker_order.status_code == 201, maker_order.text

    # Taker crosses the book and receives the unchanged base parabolic fee.
    taker_order = await client.post(
        "/api/v4/prediction/orders",
        json={
            "market_id": market["id"],
            "token_id": yes_token,
            "side": "BUY",
            "type": "LIMIT",
            "price": 0.50,
            "amount": 10,
            "time_in_force": "GTC",
        },
        headers=taker,
    )
    assert taker_order.status_code == 201, taker_order.text
    filled = taker_order.json()
    assert filled["order"]["status"] == "FILLED"
    assert len(filled["fills"]) == 1

    base_fee = compute_fee(
        Decimal(10), fee_rate_for_category("Crypto"), Decimal("0.50")
    )
    assert base_fee == Decimal("0.0500")
    assert Decimal(str(filled["fills"][0]["taker_fee"])) == base_fee

    async with AsyncSessionLocal() as session:
        fill = (await session.execute(select(TradeFill))).scalar_one()
        assert Decimal(fill.maker_fee) == base_fee
        assert Decimal(fill.taker_fee) == base_fee

    # Collateral withdrawal is untouched by AGX.
    before_withdraw = await _balance(client, taker)
    withdraw = await client.post(
        "/api/v1/collateral/withdraw", json={"amount": 100}, headers=taker
    )
    assert withdraw.status_code == 200, withdraw.text
    assert before_withdraw - await _balance(client, taker) == pytest.approx(100)

    # Settlement and payout redemption are untouched as well.
    close = await client.post(
        f"/api/v4/prediction/admin/markets/{market['id']}/close", headers=admin
    )
    assert close.status_code == 200, close.text

    propose = await client.post(
        "/api/v4/prediction/resolution/propose",
        json={"market_id": market["id"], "proposed_outcome_index": 0},
        headers=admin,
    )
    assert propose.status_code == 200, propose.text

    finalize = await client.post(
        "/api/v4/prediction/resolution/finalize",
        json={"market_id": market["id"], "winning_outcome_index": 0},
        headers=admin,
    )
    assert finalize.status_code == 200, finalize.text

    positions = (
        await client.get("/api/v4/prediction/positions", headers=taker)
    ).json()["positions"]
    winning = next(p for p in positions if p["token_id"] == yes_token)
    assert float(winning["shares"]) == 10.0

    before_redeem = await _balance(client, taker)
    redeem = await client.post(
        f"/api/v4/prediction/positions/{winning['position_id']}/redeem",
        headers=taker,
    )
    assert redeem.status_code == 200, redeem.text
    assert redeem.json()["payout_amount"] == pytest.approx(10.0)
    assert await _balance(client, taker) == pytest.approx(before_redeem + 10.0)

    # No AGX row was ever created for either participant.
    assert await _agx_rows("zero-maker@example.com") == (0, 0)
    assert await _agx_rows("zero-taker@example.com") == (0, 0)


async def test_agx_routes_stay_optional_after_a_full_trade(client: AsyncClient):
    """Reading the AGX surface after trading must not alter collateral or fees."""
    taker = await auth_headers(client, "zero-reader@example.com")
    await _deposit(client, taker, 1000)
    before = await _balance(client, taker)

    balance = await client.get("/api/v1/agx/balance", headers=taker)
    assert balance.status_code == 200
    assert balance.json()["balance"] == "0.000000000000000000"
    assert balance.json()["tier"] == "0"

    await client.post("/api/v1/agx/claim-rewards", headers=taker)
    assert await _balance(client, taker) == before
    assert await _agx_rows("zero-reader@example.com") == (1, 0)
