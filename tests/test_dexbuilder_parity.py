"""DexBuilder parity: local surfaces + proxy 503/200 behavior."""
import os
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_tags_returns_list(client: AsyncClient):
    r = await client.get("/api/v4/prediction/tags")
    assert r.status_code == 200
    assert "tags" in r.json()


async def test_bulk_prices_returns_one_entry_per_id(client: AsyncClient):
    r = await client.get("/api/v4/prediction/tokens/prices", params={"ids": ["a", "b"]})
    assert r.status_code == 200
    assert set(r.json()["prices"].keys()) == {"a", "b"}
    r2 = await client.get("/api/v4/prediction/tokens/prices", params={"ids": ""})
    assert r2.status_code == 422


async def test_usertrades_requires_auth(client: AsyncClient):
    r = await client.get("/api/v4/prediction/usertrades")
    assert r.status_code == 401
    h = await auth_headers(client, "ut@example.com")
    r2 = await client.get("/api/v4/prediction/usertrades", headers=h)
    assert r2.status_code == 200
    assert "trades" in r2.json()


async def test_settled_positions_requires_auth(client: AsyncClient):
    r = await client.get("/api/v4/prediction/positions/settled")
    assert r.status_code == 401
    h = await auth_headers(client, "sp@example.com")
    r2 = await client.get("/api/v4/prediction/positions/settled", headers=h)
    assert r2.status_code == 200
    assert "positions" in r2.json()


async def test_market_by_slug(client: AsyncClient):
    # seed an event+market via admin
    ah = await auth_headers(client, "adminmkt@example.com")
    # promote admin
    from app.db.session import AsyncSessionLocal
    from app.models.domain import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as s:
        u = (await s.execute(select(User).where(User.email == "adminmkt@example.com"))).scalar_one()
        u.is_admin = True
        await s.commit()
    ev = await client.post("/api/v4/prediction/admin/events", json={"slug": "e-slug", "title": "E"}, headers=ah)
    assert ev.status_code in (200, 201)
    mk = await client.post("/api/v4/prediction/admin/markets", json={"event_slug": "e-slug", "question": "Q?", "outcomes": ["YES", "NO"]}, headers=ah)
    assert mk.status_code in (200, 201)
    r = await client.get("/api/v4/prediction/markets/slug/e-slug")
    assert r.status_code == 200


async def test_proxy_returns_503_when_unconfigured(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("DEXBUILDER_API_KEY", raising=False)
    monkeypatch.setenv("DEXBUILDER_API_KEY", "")
    r = await client.get("/api/v4/dexbuilder/markets")
    assert r.status_code == 503
    assert r.json()["detail"] == "DEXBUILDER_NOT_CONFIGURED"