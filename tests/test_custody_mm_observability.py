"""Tests for Sprint 7.3 & 7.4: Verified deposits, ledger reconciliation, MM kill-switch/freshness, X-Request-ID & /metrics."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services.market_maker import MMConfig, compute_quotes, mm_manager
from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


async def test_verified_deposit_replay_and_double_entry_reconciliation(client: AsyncClient):
    h = await auth_headers(client, "custody73@example.com")

    r1 = await client.post(
        "/api/v1/collateral/verified-deposit",
        json={"amount": 50, "tx_hash": "0xabc123def4567890", "chain_id": 8453},
        headers=h,
    )
    assert r1.status_code == 200
    assert r1.json()["balance_str"] == "50.0000"

    # Replaying same tx_hash is rejected with 409
    r_dup = await client.post(
        "/api/v1/collateral/verified-deposit",
        json={"amount": 50, "tx_hash": "0xabc123def4567890", "chain_id": 8453},
        headers=h,
    )
    assert r_dup.status_code == 409

    # Double-entry ledger reconciliation matches exact balance
    r_rec = await client.get("/api/v1/collateral/reconcile", headers=h)
    assert r_rec.status_code == 200
    rec = r_rec.json()
    assert rec["balanced"] is True
    assert rec["expected_balance"] == "50.0000"
    assert rec["actual_balance"] == "50.0000"


async def test_mm_stale_feed_kill_switch_and_observability(client: AsyncClient):
    # Stale reference feed halts quoting
    cfg = MMConfig(desk_id="d1", market_id="m1", token_id="t1", owner_user_id="u1")
    dec = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.1, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "age_seconds": 180},
        cfg=cfg,
    )
    assert dec.action == "HALT"
    assert dec.reason == "STALE_REFERENCE_FEED"

    # Admin-only MM kill switch
    uh = await auth_headers(client, "mm_nonadmin@example.com")
    r_forbid = await client.post("/api/v1/desks/mm/kill-all", headers=uh)
    assert r_forbid.status_code == 403

    ah = await auth_headers(client, "mm_admin73@example.com")
    await make_admin("mm_admin73@example.com")
    try:
        r_kill = await client.post("/api/v1/desks/mm/kill-all", headers=ah)
        assert r_kill.status_code == 200
        assert r_kill.json()["status"] == "killed"
    finally:
        mm_manager.global_kill_switch = False

    # X-Request-ID & /metrics
    r_h = await client.get("/health", headers={"X-Request-ID": "req-test-73"})
    assert r_h.headers.get("X-Request-ID") == "req-test-73"

    r_m = await client.get("/metrics")
    assert r_m.status_code == 200
    assert "dolymarket_requests_total" in r_m.text
    assert "dolymarket_mm_active_bots" in r_m.text


async def test_mm_dry_run_env_defaults_and_force_override(monkeypatch):
    from app.api.v1.desks import MMStartRequest
    from app.services.market_maker import (
        MMConfig,
        default_mm_dry_run,
        is_mm_force_dry_run,
    )

    monkeypatch.delenv("MM_DRY_RUN", raising=False)
    monkeypatch.delenv("MM_FORCE_DRY_RUN", raising=False)
    assert is_mm_force_dry_run() is False
    assert default_mm_dry_run() is True
    assert MMConfig("d", "m", "t", "u").dry_run is True
    assert MMStartRequest(market_id="m", token_id="t").dry_run is None

    monkeypatch.setenv("MM_DRY_RUN", "false")
    assert default_mm_dry_run() is False
    assert MMConfig("d", "m", "t", "u").dry_run is False

    monkeypatch.setenv("MM_FORCE_DRY_RUN", "1")
    assert is_mm_force_dry_run() is True
    assert default_mm_dry_run() is True
    assert MMConfig("d", "m", "t", "u").dry_run is True
