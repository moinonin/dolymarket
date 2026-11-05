"""Bulk prices endpoint."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_bulk_prices_empty_list_rejected(client: AsyncClient):
    r = await client.get("/api/v4/prediction/tokens/prices", params={"ids": ""})
    assert r.status_code == 422


async def test_bulk_prices_returns_entry_per_id(client: AsyncClient):
    r = await client.get("/api/v4/prediction/tokens/prices", params={"ids": "a,b"})
    assert r.status_code == 200
    assert set(r.json()["prices"].keys()) == {"a", "b"}