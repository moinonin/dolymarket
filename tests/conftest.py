"""Shared pytest fixtures: in-memory async DB + FastAPI test client."""
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# Hermetic test environment before app import.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-1234567890abcdef")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import AsyncSessionLocal, create_test_db


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    await create_test_db()
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def app():
    from app.main import app as fastapi_app

    return fastapi_app


async def register_user(client: AsyncClient, email: str, password: str = "hunter2secret"):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    if resp.status_code == 400:  # already registered -> log in
        resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def auth_headers(client: AsyncClient, email: str, password: str = "hunter2secret"):
    data = await register_user(client, email, password)
    return {"Authorization": f"Bearer {data['access_token']}"}


async def async_session() -> AsyncIterator:
    async with AsyncSessionLocal() as s:
        yield s
