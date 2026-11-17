"""Live BTC Fear & Greed service powered by Gate.io WebSocket + REST data.

Computes the 6-channel BTC sentiment score (price momentum, realized vol
inverse, funding rate, perp basis, orderbook imbalance, taker netflow) with
EMA kinematics and early-warning regime classification.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque

import httpx
import websockets

logger = logging.getLogger(__name__)

GATE_REST_BASE = "https://api.gateio.ws/api/v4"
GATE_FUTURES_WS = "wss://fx-ws.gateio.ws/v4/ws/usdt"
CONTRACT = "BTC_USDT"
DVOL_FALLBACK_FLOOR = 30.0
TRADE_WINDOW = 500
TOP_LEVELS = 25

PROFILE_WEIGHTS: dict[str, list[float]] = {
    # channel order: price_momentum, volatility_inv, funding_rate, perp_basis, orderbook_imbalance, exchange_netflow
    "balanced": [0.25, 0.20, 0.15, 0.15, 0.15, 0.10],
    "momentum": [0.45, 0.10, 0.10, 0.15, 0.10, 0.10],
    "vol_conservative": [0.15, 0.40, 0.10, 0.10, 0.15, 0.10],
    "microstructure": [0.15, 0.15, 0.10, 0.10, 0.30, 0.20],
}


def _clip01(val: float) -> float:
    return float(max(0.0, min(1.0, val)))


def classify_sentiment(score: float) -> str:
    if score < 20.0:
        return "EXTREME_FEAR"
    if score < 45.0:
        return "FEAR"
    if score <= 55.0:
        return "NEUTRAL"
    if score <= 80.0:
        return "GREED"
    return "EXTREME_GREED"


@dataclass
class BTCFearGreedReading:
    timestamp: float
    score_0_100: float
    sentiment_label: str
    structural_stability: float
    regime_state: str
    ewi: float
    v_alpha: float
    m_alpha: float
    btc_price: float
    funding_8h_bps: float
    return_14d_pct: float
    dvol: float
    bid_ask_imbalance: float
    early_warning: bool
    profile: str = "balanced"
    source: str = "gate.io"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GateLiveState:
    """Rolling BTC futures state fed by Gate.io REST + WebSocket."""

    def __init__(self) -> None:
        self.btc_price: float = 0.0
        self.return_14d_pct: float = 0.0
        self.dvol: float = DVOL_FALLBACK_FLOOR
        self.funding_8h_bps: float = 0.0
        self.basis_ann_pct: float = 0.0
        self.book_imbalance: float = 0.0
        self.trades: Deque[tuple[float, float, str]] = deque(maxlen=TRADE_WINDOW)
        self.last_rest_at: float = 0.0

    def on_orderbook(self, bids: list[Any], asks: list[Any]) -> None:
        bid_sz = 0.0
        ask_sz = 0.0
        for level in bids[:TOP_LEVELS]:
            if isinstance(level, dict):
                bid_sz += abs(float(level.get("s", 0.0)))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                bid_sz += abs(float(level[1]))
        for level in asks[:TOP_LEVELS]:
            if isinstance(level, dict):
                ask_sz += abs(float(level.get("s", 0.0)))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                ask_sz += abs(float(level[1]))
        total = bid_sz + ask_sz
        if total > 0:
            self.book_imbalance = (bid_sz - ask_sz) / total

    def on_trades(self, rows: list[dict[str, Any]]) -> None:
        for t in rows:
            px = float(t.get("price", 0.0) or 0.0)
            sz_raw = float(t.get("size", 0.0) or 0.0)
            # Gate.io futures trades: positive size = buy, negative size = sell
            side = "B" if sz_raw >= 0 else "S"
            if px > 0:
                self.btc_price = px
            self.trades.append((px, abs(sz_raw), side))

    def netflow_proxy(self) -> float:
        """Positive = sell-side taker pressure (fear), negative = buy-side (greed)."""
        sell = sum(sz for _px, sz, side in self.trades if side == "S")
        buy = sum(sz for _px, sz, side in self.trades if side == "B")
        # Gate.io BTC_USDT contract size is 0.0001 BTC per contract
        return (sell - buy) * 0.0001


class _ProfileKinematics:
    """Per-profile EMA velocity/momentum and Early Warning Index tracker."""

    def __init__(self, profile: str = "balanced", alpha: float = 0.35) -> None:
        self.profile = profile
        self.weights = PROFILE_WEIGHTS[profile]
        self.alpha = alpha
        self.prev_norm: float | None = None
        self.v_alpha: float = 0.0
        self.m_alpha: float = 0.0

    def compute(self, state: GateLiveState) -> BTCFearGreedReading:
        mom = _clip01((state.return_14d_pct + 25.0) / 50.0)
        vol_inv = _clip01(1.0 - (state.dvol - 30.0) / 80.0)
        funding = _clip01((state.funding_8h_bps + 5.0) / 20.0)
        basis = _clip01((state.basis_ann_pct + 10.0) / 40.0)
        ob = _clip01((state.book_imbalance + 1.0) / 2.0)
        flow = _clip01(0.5 - state.netflow_proxy() / 200.0)

        vec = [mom, vol_inv, funding, basis, ob, flow]
        norm_score = sum(v * w for v, w in zip(vec, self.weights))
        score = norm_score * 100.0

        mean_v = sum(vec) / len(vec)
        dispersion = math.sqrt(sum((v - mean_v) ** 2 for v in vec) / len(vec))
        extremeness = abs(norm_score - 0.5) * 2.0
        stability = _clip01(1.0 - 0.70 * extremeness - 0.30 * min(1.0, dispersion * 2.5))

        if self.prev_norm is not None:
            delta = norm_score - self.prev_norm
            self.v_alpha = self.alpha * delta + (1.0 - self.alpha) * self.v_alpha
            self.m_alpha = self.alpha * abs(delta) + (1.0 - self.alpha) * self.m_alpha
        self.prev_norm = norm_score

        ewi = _clip01(0.55 * (1.0 - stability) + 0.45 * min(1.0, abs(self.v_alpha) * 10.0 + self.m_alpha * 5.0))
        early_warning = ewi >= 0.65 or self.v_alpha <= -0.05
        regime_state = "CRITICAL" if ewi >= 0.75 else "ELEVATED" if ewi >= 0.45 else "STABLE"

        return BTCFearGreedReading(
            timestamp=time.time(),
            score_0_100=round(score, 2),
            sentiment_label=classify_sentiment(score),
            structural_stability=round(stability, 4),
            regime_state=regime_state,
            ewi=round(ewi, 4),
            v_alpha=round(self.v_alpha, 5),
            m_alpha=round(self.m_alpha, 5),
            btc_price=round(state.btc_price, 2),
            funding_8h_bps=round(state.funding_8h_bps, 3),
            return_14d_pct=round(state.return_14d_pct, 2),
            dvol=round(state.dvol, 2),
            bid_ask_imbalance=round(state.book_imbalance, 4),
            early_warning=early_warning,
            profile=self.profile,
        )


class BTCFearGreedService:
    """Manages Gate.io live feed and broadcasts Fear & Greed readings."""

    def __init__(self) -> None:
        self.state = GateLiveState()
        self._kinematics: dict[str, _ProfileKinematics] = {
            p: _ProfileKinematics(p) for p in PROFILE_WEIGHTS
        }
        self._latest: dict[str, BTCFearGreedReading] = {}
        self._clients: set[tuple[Any, str]] = set()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def refresh_rest(self) -> None:
        """Fetch 10s candles (1h window), contract funding/mark, and orderbook from Gate.io."""
        async with httpx.AsyncClient(base_url=GATE_REST_BASE, timeout=10.0) as client:
            candles_r, contract_r, book_r, trades_r = await asyncio.gather(
                client.get("/futures/usdt/candlesticks", params={"contract": CONTRACT, "interval": "10s", "limit": 360}),
                client.get(f"/futures/usdt/contracts/{CONTRACT}"),
                client.get("/futures/usdt/order_book", params={"contract": CONTRACT, "limit": TOP_LEVELS}),
                client.get("/futures/usdt/trades", params={"contract": CONTRACT, "limit": 100}),
            )
            candles_r.raise_for_status()
            contract_r.raise_for_status()
            candles = candles_r.json()
            contract = contract_r.json()

            closes = [float(c["c"]) for c in candles if c.get("c")]
            if len(closes) >= 2:
                self.state.return_14d_pct = (closes[-1] / closes[0] - 1.0) * 100.0
                log_rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
                if len(log_rets) >= 2:
                    mean = sum(log_rets) / len(log_rets)
                    var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
                    # Annualize 10s log returns: 365 * 24 * 360 = 3,153,600 intervals/year
                    self.state.dvol = max(DVOL_FALLBACK_FLOOR, math.sqrt(var * 3_153_600) * 100.0)

            mark_px = float(contract.get("mark_price") or 0.0)
            index_px = float(contract.get("index_price") or 0.0)
            if mark_px > 0:
                self.state.btc_price = mark_px
            if mark_px > 0 and index_px > 0:
                self.state.basis_ann_pct = ((mark_px - index_px) / index_px) * 100.0 * 365.0
            self.state.funding_8h_bps = float(contract.get("funding_rate") or 0.0) * 10000.0

            if book_r.status_code == 200:
                bk = book_r.json()
                self.state.on_orderbook(bk.get("bids", []), bk.get("asks", []))
            if trades_r.status_code == 200 and not self.state.trades:
                tr = trades_r.json()
                if isinstance(tr, list):
                    self.state.on_trades(tr)

            self.state.last_rest_at = time.time()
            self._recompute_all()

    def _recompute_all(self) -> None:
        for prof, kin in self._kinematics.items():
            self._latest[prof] = kin.compute(self.state)

    async def get_latest(self, profile: str = "microstructure") -> dict[str, Any]:
        if profile not in PROFILE_WEIGHTS:
            profile = "microstructure"
        async with self._lock:
            if profile not in self._latest or (time.time() - self.state.last_rest_at > 10.0):
                try:
                    await self.refresh_rest()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Gate.io REST refresh failed: %s", exc)
                    if profile not in self._latest:
                        self._recompute_all()
        return self._latest[profile].to_dict()

    def ensure_stream(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._ws_loop())

    async def register(self, ws: Any, profile: str) -> None:
        self._clients.add((ws, profile))
        self.ensure_stream()

    def unregister(self, ws: Any, profile: str) -> None:
        self._clients.discard((ws, profile))

    async def _broadcast(self) -> None:
        for ws, prof in list(self._clients):
            reading = self._latest.get(prof) or self._latest.get("balanced")
            if not reading:
                continue
            try:
                await ws.send_json(reading.to_dict())
            except Exception:  # noqa: BLE001
                self._clients.discard((ws, prof))

    async def _ws_loop(self) -> None:
        while self._clients:
            try:
                async with websockets.connect(GATE_FUTURES_WS, open_timeout=10, ping_interval=20) as ws:
                    now = int(time.time())
                    await ws.send(json.dumps({
                        "time": now,
                        "channel": "futures.trades",
                        "event": "subscribe",
                        "payload": [CONTRACT],
                    }))
                    await ws.send(json.dumps({
                        "time": now,
                        "channel": "futures.order_book",
                        "event": "subscribe",
                        "payload": [CONTRACT, "20", "0"],
                    }))
                    last_emit = 0.0
                    async for raw in ws:
                        if not self._clients:
                            break
                        msg = json.loads(raw)
                        if msg.get("event") != "update":
                            continue
                        ch = msg.get("channel")
                        res = msg.get("result")
                        if ch == "futures.trades" and isinstance(res, list):
                            self.state.on_trades(res)
                        elif ch == "futures.order_book" and isinstance(res, dict):
                            self.state.on_orderbook(res.get("bids", []), res.get("asks", []))
                        if time.time() - self.state.last_rest_at > 10.0:
                            try:
                                await self.refresh_rest()
                            except Exception:  # noqa: BLE001
                                pass
                        if time.time() - last_emit >= 0.25:
                            self._recompute_all()
                            await self._broadcast()
                            last_emit = time.time()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gate.io WS disconnected: %s", exc)
                await asyncio.sleep(3.0)


fear_greed_service = BTCFearGreedService()
