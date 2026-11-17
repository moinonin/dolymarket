#!/usr/bin/env python3
"""Backtest calibration for Fear & Greed Market Maker against Gate.io BTC_USDT candles.

Simulates rolling 5-minute binary Up/Down contracts over historical Gate.io 10s
and 1m futures candles, sweeping (k_fg, k_vel, gamma, ewi_critical) to measure
PnL, fill rate, and EWI halt effectiveness.
"""
from __future__ import annotations

import asyncio
import math
from decimal import Decimal
from itertools import product

import httpx

from app.services.fear_greed import DVOL_FALLBACK_FLOOR, GATE_REST_BASE, GateLiveState, _ProfileKinematics
from app.services.market_maker import MMConfig, compute_quotes


async def fetch_candles(interval: str, limit: int) -> list[dict]:
    async with httpx.AsyncClient(base_url=GATE_REST_BASE, timeout=10.0) as client:
        r = await client.get(
            "/futures/usdt/candlesticks",
            params={"contract": "BTC_USDT", "interval": interval, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


def build_readings(candles: list[dict], window: int = 30, ann_factor: float = 3_153_600.0) -> list[tuple[float, dict]]:
    closes = [float(c["c"]) for c in candles]
    vols = [float(c["v"]) for c in candles]
    state = GateLiveState()
    kin = _ProfileKinematics("microstructure")
    out: list[tuple[float, dict]] = []

    for i in range(window, len(closes)):
        win_c = closes[i - window : i + 1]
        win_v = vols[i - window : i + 1]
        state.btc_price = win_c[-1]
        state.return_14d_pct = (win_c[-1] / win_c[0] - 1.0) * 100.0
        log_rets = [math.log(win_c[j] / win_c[j - 1]) for j in range(1, len(win_c)) if win_c[j - 1] > 0]
        if len(log_rets) >= 2:
            mean = sum(log_rets) / len(log_rets)
            var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
            state.dvol = max(DVOL_FALLBACK_FLOOR, math.sqrt(var * ann_factor) * 100.0)
        # Proxy orderbook imbalance from recent bar direction & volume
        up_v = sum(win_v[j] for j in range(1, len(win_c)) if win_c[j] >= win_c[j - 1])
        dn_v = sum(win_v[j] for j in range(1, len(win_c)) if win_c[j] < win_c[j - 1])
        tot_v = up_v + dn_v
        state.book_imbalance = (up_v - dn_v) / tot_v if tot_v > 0 else 0.0
        reading = kin.compute(state).to_dict()
        out.append((win_c[-1], reading))
    return out


def simulate(
    series: list[tuple[float, dict]],
    *,
    horizon_steps: int,
    k_fg: float,
    k_vel: float,
    gamma: float,
    ewi_critical: float,
) -> dict:
    cfg = MMConfig(
        desk_id="calib",
        market_id="btc-5m",
        token_id="btc-up",
        owner_user_id="calib",
        k_fg=k_fg,
        k_vel=k_vel,
        gamma=gamma,
        ewi_critical=ewi_critical,
    )
    pnl = 0.0
    fills = 0
    halts = 0
    inventory = Decimal("0")
    halted = False

    # Step through non-overlapping or rolling 5m windows
    for i in range(0, len(series) - horizon_steps):
        px_now, reading = series[i]
        px_fut, _ = series[i + horizon_steps]
        # Synthetic fair market mid around 0.50 + slight drift from recent move
        dec = compute_quotes(
            book_mid=Decimal("0.50"),
            inventory=inventory,
            reading=reading,
            cfg=cfg,
            was_halted=halted,
        )
        halted = dec.halted
        if dec.action == "HALT":
            halts += 1
            continue

        # Binary settlement at t + horizon_steps: 1.0 if Up, 0.0 if Down
        settle = 1.0 if px_fut > px_now else 0.0
        # Simple adverse-selection / fill model:
        # Bid fills if market dips slightly or settles down; Ask fills if market rises or settles up
        bid_px = float(dec.bid_price) if dec.bid_price is not None else None
        ask_px = float(dec.ask_price) if dec.ask_price is not None else None
        sz = float(dec.quote_size)

        if bid_px is not None and settle <= 0.5 + (0.5 - bid_px):
            # Bought at bid_px, settled at settle
            pnl += (settle - bid_px) * sz
            fills += 1
            inventory = max(-cfg.max_inventory, min(cfg.max_inventory, inventory + Decimal("1")))
        if ask_px is not None and settle >= 0.5 - (ask_px - 0.5):
            # Sold at ask_px, settled at settle
            pnl += (ask_px - settle) * sz
            fills += 1
            inventory = max(-cfg.max_inventory, min(cfg.max_inventory, inventory - Decimal("1")))

    return {
        "k_fg": k_fg,
        "k_vel": k_vel,
        "gamma": gamma,
        "ewi_crit": ewi_critical,
        "pnl": round(pnl, 2),
        "fills": fills,
        "halts": halts,
    }


async def main() -> None:
    candles_10s = await fetch_candles("10s", 500)
    candles_1m = await fetch_candles("1m", 600)
    print(f"Fetched Gate.io BTC_USDT candles: 10s={len(candles_10s)}, 1m={len(candles_1m)}")

    s10 = build_readings(candles_10s, window=30, ann_factor=3_153_600.0)
    s1m = build_readings(candles_1m, window=30, ann_factor=525_600.0)

    for label, series, horizon in [("10s (5m=30 steps)", s10, 30), ("1m (5m=5 steps)", s1m, 5)]:
        results = [
            simulate(series, horizon_steps=horizon, k_fg=kf, k_vel=kv, gamma=gm, ewi_critical=ec)
            for kf, kv, gm, ec in product(
                [0.02, 0.04, 0.06],
                [0.15, 0.25],
                [0.02, 0.03, 0.05],
                [0.70, 0.75, 0.80],
            )
        ]
        results.sort(key=lambda r: r["pnl"], reverse=True)
        print(f"\nTop 5 configs on {label}:")
        for r in results[:5]:
            print(" ", r)


if __name__ == "__main__":
    asyncio.run(main())
