"""Tests for Fear & Greed Market-Making Pro Desk strategy & control routes."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.market_maker import MMConfig, compute_quotes, mm_manager
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


def _cfg(**overrides) -> MMConfig:
    base = dict(
        desk_id="desk-1",
        market_id="mkt-1",
        token_id="tok-1",
        owner_user_id="user-1",
        base_half_spread=Decimal("0.02"),
        quote_size=Decimal("10"),
        max_inventory=Decimal("100"),
        tick_size=Decimal("0.01"),
    )
    base.update(overrides)
    return MMConfig(**base)


async def test_stable_neutral_quotes_are_symmetric():
    dec = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.20, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False},
        cfg=_cfg(),
    )
    assert dec.action == "QUOTE"
    assert dec.bid_price == Decimal("0.48")
    assert dec.ask_price == Decimal("0.52")
    assert dec.quote_size == Decimal("10.0000")
    assert dec.halted is False


async def test_elevated_regime_widens_spread_and_halves_size():
    dec = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.55, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "ELEVATED", "early_warning": False},
        cfg=_cfg(),
    )
    assert dec.action == "QUOTE"
    assert dec.bid_price == Decimal("0.45")
    assert dec.ask_price == Decimal("0.55")
    assert dec.quote_size == Decimal("5.0000")


async def test_critical_ewi_halts_and_hysteresis_holds_until_resume():
    cfg = _cfg()
    halt = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.78, "score_0_100": 25.0, "v_alpha": -0.06, "regime_state": "CRITICAL", "early_warning": True},
        cfg=cfg,
    )
    assert halt.action == "HALT"
    assert halt.bid_price is None
    assert halt.ask_price is None
    assert halt.halted is True

    # Hysteresis: ewi=0.60 >= ewi_resume (0.55) stays halted
    wait = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.60, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "ELEVATED", "early_warning": False},
        cfg=cfg,
        was_halted=True,
    )
    assert wait.action == "HALT"
    assert wait.reason == "HYSTERESIS_WAIT"

    # Below ewi_resume (0.55) resumes quoting
    resumed = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("0"),
        reading={"ewi": 0.40, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False},
        cfg=cfg,
        was_halted=True,
    )
    assert resumed.action == "QUOTE"
    assert resumed.halted is False


async def test_inventory_skew_and_hard_cap():
    cfg = _cfg(max_inventory=Decimal("100"))
    skewed = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("50"),
        reading={"ewi": 0.20, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False},
        cfg=cfg,
    )
    assert skewed.fair_value < Decimal("0.50")

    capped = compute_quotes(
        book_mid=Decimal("0.50"),
        inventory=Decimal("100"),
        reading={"ewi": 0.20, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False},
        cfg=cfg,
    )
    assert capped.bid_price is None
    assert capped.ask_price is not None


async def test_sentiment_skew_respects_crypto_skew_flag():
    reading = {"ewi": 0.20, "score_0_100": 90.0, "v_alpha": 0.02, "regime_state": "STABLE", "early_warning": False}
    with_skew = compute_quotes(book_mid=Decimal("0.50"), inventory=Decimal("0"), reading=reading, cfg=_cfg(crypto_skew=True))
    no_skew = compute_quotes(book_mid=Decimal("0.50"), inventory=Decimal("0"), reading=reading, cfg=_cfg(crypto_skew=False))
    assert with_skew.fair_value > Decimal("0.50")
    assert no_skew.fair_value == Decimal("0.5000")


async def test_desk_mm_start_status_stop_and_authz(client):
    owner_headers = await auth_headers(client, "mm_owner@example.com")
    other_headers = await auth_headers(client, "mm_other@example.com")

    created = await client.post(
        "/api/v1/desks",
        json={"name": "FG Desk", "slug": "fg-desk-mm", "description": "Fear & Greed MM", "pro": False},
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    created_data = created.json()
    desk_id = (created_data.get("desk") or created_data)["id"]

    fake_reading = {
        "ewi": 0.22,
        "score_0_100": 62.0,
        "v_alpha": 0.01,
        "regime_state": "STABLE",
        "early_warning": False,
    }
    with patch("app.services.market_maker.fear_greed_service.get_latest", new=AsyncMock(return_value=fake_reading)):
        # Non-owner forbidden
        r_forbid = await client.post(
            f"/api/v1/desks/{desk_id}/mm/start",
            json={"market_id": "m1", "token_id": "t1", "dry_run": True},
            headers=other_headers,
        )
        assert r_forbid.status_code == 403

        r_start = await client.post(
            f"/api/v1/desks/{desk_id}/mm/start",
            json={"market_id": "m1", "token_id": "t1", "dry_run": True},
            headers=owner_headers,
        )
        assert r_start.status_code == 200
        body = r_start.json()
        assert body["running"] is True
        assert body["dry_run"] is True
        assert body["ticks"] >= 1
        assert body["last_decision"]["action"] == "QUOTE"

        r_status = await client.get(f"/api/v1/desks/{desk_id}/mm/status", headers=owner_headers)
        assert r_status.status_code == 200
        assert r_status.json()["running"] is True

        r_stop = await client.post(f"/api/v1/desks/{desk_id}/mm/stop", headers=owner_headers)
        assert r_stop.status_code == 200
        assert r_stop.json()["running"] is False

    # Cleanup manager registry
    await mm_manager.stop(desk_id)


async def test_mm_persists_and_resumes_across_restart(client):
    owner_headers = await auth_headers(client, "mm_persist@example.com")
    created = await client.post(
        "/api/v1/desks",
        json={"name": "Persist Desk", "slug": "persist-desk-mm", "description": "Persist MM", "pro": False},
        headers=owner_headers,
    )
    assert created.status_code == 201
    created_data = created.json()
    desk_id = (created_data.get("desk") or created_data)["id"]

    fake_reading = {
        "ewi": 0.25,
        "score_0_100": 55.0,
        "v_alpha": 0.0,
        "regime_state": "STABLE",
        "early_warning": False,
    }
    with patch("app.services.market_maker.fear_greed_service.get_latest", new=AsyncMock(return_value=fake_reading)):
        r_start = await client.post(
            f"/api/v1/desks/{desk_id}/mm/start",
            json={"market_id": "m1", "token_id": "t1", "dry_run": True},
            headers=owner_headers,
        )
        assert r_start.status_code == 200

        # Simulate server shutdown without disabling DB persistence
        await mm_manager.stop_all()
        assert mm_manager.get_status(desk_id)["running"] is False

        # Simulate boot resume
        resumed = await mm_manager.resume_enabled()
        assert resumed == 1
        assert mm_manager.get_status(desk_id)["running"] is True

        # Explicit stop disables DB persistence
        r_stop = await client.post(f"/api/v1/desks/{desk_id}/mm/stop", headers=owner_headers)
        assert r_stop.status_code == 200
        assert await mm_manager.resume_enabled() == 0


async def test_pre_expiry_local_jump_daily_loss_and_usdc_exposure():
    cfg = _cfg(max_usdc_exposure=Decimal("10"), daily_loss_limit_usdc=Decimal("25"), expiry_pull_minutes=15)
    stable = {"ewi": 0.20, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False}

    # Pre-expiry pull
    exp = compute_quotes(book_mid=Decimal("0.50"), inventory=Decimal("0"), reading=stable, cfg=cfg, seconds_to_expiry=600)
    assert exp.action == "HALT" and exp.reason == "PRE_EXPIRY_PULL"

    # Local toxicity jump (>= 0.08)
    jmp = compute_quotes(
        book_mid=Decimal("0.60"), inventory=Decimal("0"), reading=stable, cfg=cfg, prev_book_mid=Decimal("0.50")
    )
    assert jmp.action == "HALT" and jmp.reason == "LOCAL_TOXICITY_JUMP"

    # Daily loss limit
    loss = compute_quotes(
        book_mid=Decimal("0.50"), inventory=Decimal("0"), reading=stable, cfg=cfg, realized_loss_usdc=Decimal("25")
    )
    assert loss.action == "HALT" and loss.reason == "DAILY_LOSS_LIMIT"

    # Desk portfolio-wide total exposure cap
    desk_cap_cfg = _cfg(desk_max_total_exposure_usdc=Decimal("100"))
    desk_cap = compute_quotes(
        book_mid=Decimal("0.50"), inventory=Decimal("0"), reading=stable, cfg=desk_cap_cfg, desk_exposure_usdc=Decimal("100")
    )
    assert desk_cap.action == "HALT" and desk_cap.reason == "DESK_TOTAL_EXPOSURE_CAP"

    # USDC exposure cap clamps size (remaining 10 / 0.50 = 20, or with inv=16 -> used=8, remaining=2 -> max_shares=4)
    capped = compute_quotes(book_mid=Decimal("0.50"), inventory=Decimal("16"), reading=stable, cfg=cfg)
    assert capped.action == "QUOTE"
    assert capped.quote_size <= Decimal("4.5")


async def test_multi_market_per_desk_concurrent_bots(client):
    owner_headers = await auth_headers(client, "mm_multi@example.com")
    created = await client.post(
        "/api/v1/desks",
        json={"name": "Multi Desk", "slug": "multi-desk-mm", "description": "Multi MM", "pro": False},
        headers=owner_headers,
    )
    assert created.status_code == 201
    created_data = created.json()
    desk_id = (created_data.get("desk") or created_data)["id"]

    fake_reading = {"ewi": 0.20, "score_0_100": 50.0, "v_alpha": 0.0, "regime_state": "STABLE", "early_warning": False}
    with patch("app.services.market_maker.fear_greed_service.get_latest", new=AsyncMock(return_value=fake_reading)):
        r1 = await client.post(
            f"/api/v1/desks/{desk_id}/mm/start",
            json={"market_id": "m1", "token_id": "t1", "dry_run": True},
            headers=owner_headers,
        )
        r2 = await client.post(
            f"/api/v1/desks/{desk_id}/mm/start",
            json={"market_id": "m2", "token_id": "t2", "dry_run": True},
            headers=owner_headers,
        )
        assert r1.status_code == 200 and r2.status_code == 200
        status = (await client.get(f"/api/v1/desks/{desk_id}/mm/status", headers=owner_headers)).json()
        assert len(status["bots"]) == 2
        await client.post(f"/api/v1/desks/{desk_id}/mm/stop", headers=owner_headers)
