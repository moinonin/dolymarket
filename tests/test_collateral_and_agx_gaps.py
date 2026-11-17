"""Tests for pre-Sprint 6 gap fixes: demo collateral prod guard, idempotency, AGX bond & epoch rollover."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db.session import AsyncSessionLocal
from app.models.domain import AgxRewardEpoch
from app.services import agx
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_demo_collateral_guard_and_idempotency(client: AsyncClient, monkeypatch):
    h = await auth_headers(client, "collat_guard@example.com")

    # Idempotency-Key deduplicates repeated deposit
    r1 = await client.post(
        "/api/v1/collateral/deposit",
        json={"amount": 25},
        headers={**h, "Idempotency-Key": "dep-key-1"},
    )
    assert r1.status_code == 200
    assert r1.json()["balance"] == 25.0

    r2 = await client.post(
        "/api/v1/collateral/deposit",
        json={"amount": 25},
        headers={**h, "Idempotency-Key": "dep-key-1"},
    )
    assert r2.status_code == 200
    assert r2.json()["balance"] == 25.0

    # Disabled when ENABLE_DEMO_COLLATERAL=0
    monkeypatch.setenv("ENABLE_DEMO_COLLATERAL", "0")
    r3 = await client.post("/api/v1/collateral/deposit", json={"amount": 10}, headers=h)
    assert r3.status_code == 403
    assert "DEMO_COLLATERAL_DISABLED" in r3.json()["detail"]


async def test_community_market_optional_agx_bond(client: AsyncClient):
    h = await auth_headers(client, "agx_comm@example.com")
    r = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "AGX Bonded Market",
            "question": "Will AGX bond lock?",
            "category": "Crypto",
            "outcomes": ["YES", "NO"],
            "resolution_criteria": "Resolves YES per official feed.",
            "bond_with_agx": True,
        },
        headers=h,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "AGX_INSUFFICIENT_GATE"


async def test_distribute_matured_epochs():
    async with AsyncSessionLocal() as s:
        ep = AgxRewardEpoch(
            epoch_number=99,
            total_fees_collected=Decimal("10.000000000000000000"),
            started_at=datetime.now(UTC) - timedelta(hours=25),
            distributed=False,
        )
        s.add(ep)
        await s.commit()

        count = await agx.distribute_matured_epochs(s)
        await s.commit()
        assert count == 1
        assert await agx.distribute_matured_epochs(s) == 0
