"""Tests for Sprint 7.2: Refresh rotation, JTI revocation, API-key revoke, WS single-use tickets, and bounded rate limiter."""
import time

import pytest
from httpx import AsyncClient

from app.core import ratelimit, security

pytestmark = pytest.mark.asyncio


async def test_refresh_rotation_and_logout_jti_revocation(client: AsyncClient):
    r_reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "sec72@example.com", "password": "hunter2secret"},
    )
    assert r_reg.status_code == 201
    tok1 = r_reg.json()["access_token"]
    assert "dolymarket_refresh" in r_reg.cookies

    # Refresh rotates cookie & issues new token
    old_refresh = r_reg.cookies["dolymarket_refresh"]
    r_ref = await client.post("/api/v1/auth/refresh", cookies={"dolymarket_refresh": old_refresh})
    assert r_ref.status_code == 200
    tok2 = r_ref.json()["access_token"]

    # Reusing rotated refresh token is rejected
    r_replay = await client.post("/api/v1/auth/refresh", cookies={"dolymarket_refresh": old_refresh})
    assert r_replay.status_code == 401

    # Logout revokes tok2 JTI immediately
    r_out = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tok2}"})
    assert r_out.status_code == 200
    r_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok2}"})
    assert r_me.status_code == 401
    # tok1 still has its own non-revoked JTI unless explicitly logged out
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok1}"})).status_code == 200


async def test_api_key_revocation_and_ws_single_use_ticket(client: AsyncClient):
    r_reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "wsticket@example.com", "password": "hunter2secret"},
    )
    tok = r_reg.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # Issue + revoke API key
    r_key = await client.post("/api/v1/auth/api-key", headers=h)
    api_key = r_key.json()["api_key"]
    r_del = await client.delete("/api/v1/auth/api-key", headers=h)
    assert r_del.status_code == 200

    secret = security.split_api_key(api_key)
    ts = str(int(time.time()))
    sig = security.compute_hmac_signature(secret, ts, "GET", "/api/v1/auth/me", b"")
    r_hmac = await client.get(
        "/api/v1/auth/me",
        headers={"X-API-KEY": api_key, "X-TIMESTAMP": ts, "X-SIGNATURE": sig},
    )
    assert r_hmac.status_code == 401

    # Single-use WS ticket
    r_tk = await client.post("/api/v1/auth/ws-ticket", headers=h)
    assert r_tk.status_code == 200
    ticket = r_tk.json()["ticket"]
    uid = security.consume_ws_ticket(ticket)
    assert uid is not None
    assert security.consume_ws_ticket(ticket) is None


async def test_rate_limiter_bounds_bucket_memory(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_BUCKETS", 8)
    lim = ratelimit.TokenBucketLimiter()
    for i in range(20):
        lim.allow(f"ip:{i}", 10.0, 10.0)
    assert len(lim._buckets) <= 8
