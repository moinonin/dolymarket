"""Live DexBuilder market data: normalization, caching and fault tolerance.

DexBuilder serves the public prediction surfaces (markets, events, order books,
candles, tags, trades, server time) **without credentials**. This module turns
those upstream payloads into the shapes the Dolymarket frontend already
understands, caches them for a short TTL and opens a circuit breaker when the
upstream is unhealthy so the UI degrades instead of hanging.

All numeric parsing and derivation is performed with :class:`~decimal.Decimal`;
binary floating point is only used at the JSON boundary.
"""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from app.services.dexbuilder import DexBuilderClient, get_config

#: Upstream does not publish tick size / minimum order size for public markets.
#: They are display-only values on read-only live markets.
DEFAULT_TICK_SIZE = Decimal("0.01")
DEFAULT_MIN_ORDER_SIZE = Decimal("1")

#: Seconds a successful upstream read stays fresh.
CACHE_TTL_SECONDS = 10.0
#: Consecutive failures before the circuit opens.
FAILURE_THRESHOLD = 3
#: Seconds the circuit stays open before a probe is allowed through.
CIRCUIT_OPEN_SECONDS = 30.0
#: Upstream allows at most 14 days of price history per request.
MAX_HISTORY_WINDOW_MS = 14 * 24 * 60 * 60 * 1000


class LiveUnavailableError(RuntimeError):
    """Raised when the upstream cannot be reached or keeps failing."""


# ---------------------------------------------------------------------------
# Numeric helpers (Decimal first, JSON boundary last)
# ---------------------------------------------------------------------------


def to_decimal(value: Any) -> Decimal | None:
    """Parse an upstream numeric (often a string) into a Decimal."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def to_float(value: Any) -> float | None:
    """Serialize a Decimal (or upstream numeric) for JSON output."""
    parsed = to_decimal(value)
    return None if parsed is None else float(parsed)


def _label(value: Any) -> str:
    """DexBuilder returns localized label objects; prefer the English label."""
    if isinstance(value, dict):
        for key in ("en", "cn", "tw"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        return ""
    if value is None:
        return ""
    return str(value)


def _iso(seconds: Any) -> str | None:
    parsed = to_decimal(seconds)
    if parsed is None:
        return None
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(float(parsed), tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_status(status: str | None) -> str:
    """Map Dolymarket status filters onto the upstream status values.

    Upstream only understands ``active`` and ``closed`` (anything else answers
    HTTP 400), and an empty status returns closed markets.
    """
    if not status:
        return "closed"
    value = str(status).strip().lower()
    if value in ("active", "open"):
        return "active"
    if value in ("closed", "resolved", "settled", "historical"):
        return "closed"
    return value


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def normalize_tags(raw: Any) -> list[str]:
    """``{"items": [{"slug": ..., "label": {"en": ...}}]}`` -> ``["Tag", ...]``."""
    items = raw.get("items", []) if isinstance(raw, dict) else (raw or [])
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            label = _label(item.get("label")) or str(item.get("slug") or "")
        else:
            label = str(item)
        if label:
            out.append(label)
    return sorted(set(out))


def normalize_market(raw: dict) -> dict:
    """Upstream market -> Dolymarket market payload (read-only, live)."""
    outcomes_raw = raw.get("outcomes") or []
    outcomes: list[str] = []
    tokens: list[dict] = []
    prices: dict[str, float] = {}
    outcome_prices: list[Decimal | None] = []
    for index, outcome in enumerate(outcomes_raw):
        if isinstance(outcome, dict):
            symbol = str(outcome.get("outcome") or f"Outcome {index + 1}")
            token_id = str(outcome.get("token_id") or outcome.get("clob_token_id") or "")
            price = to_decimal(outcome.get("price"))
        else:
            symbol = str(outcome)
            token_id = ""
            price = None
        outcomes.append(symbol)
        outcome_prices.append(price)
        tokens.append(
            {
                "token_id": token_id,
                "outcome_index": index,
                "symbol": symbol,
                "price": None if price is None else float(price),
            }
        )
        if token_id and price is not None:
            prices[token_id] = float(price)

    best_bid = to_decimal(raw.get("best_bid"))
    best_ask = to_decimal(raw.get("best_ask"))
    last_trade = to_decimal(raw.get("last_trade_price"))
    mid_price: Decimal | None = None
    if best_bid is not None and best_ask is not None:
        mid_price = (best_bid + best_ask) / Decimal(2)

    tags = raw.get("tags")
    if isinstance(tags, list):
        tag_labels = sorted(
            {
                _label(t.get("label")) if isinstance(t, dict) else str(t)
                for t in tags
                if t
            }
        )
    else:
        tag_labels = []

    status = str(raw.get("status") or "active").upper()
    closed = bool(raw.get("closed")) or status == "CLOSED"
    winning_index, winning_symbol = _winning_outcome(outcome_prices, outcomes, closed)

    return {
        "id": str(raw.get("market_id") or raw.get("id") or ""),
        "event_id": str(raw.get("event_id") or ""),
        "condition_id": raw.get("condition_id"),
        "question": str(raw.get("title") or raw.get("question") or ""),
        "event_title": raw.get("event_title"),
        "slug": raw.get("slug"),
        "outcomes": outcomes,
        "tokens": tokens,
        "prices": prices,
        "tick_size": float(DEFAULT_TICK_SIZE),
        "min_order_size": float(DEFAULT_MIN_ORDER_SIZE),
        "status": status,
        "neg_risk": False,
        "winning_outcome_index": winning_index,
        "winning_outcome": winning_symbol,
        "resolved": closed,
        "created_at": _iso(raw.get("start_time")),
        "start_time": raw.get("start_time"),
        "end_time": raw.get("end_time"),
        "category": raw.get("category") or "",
        "tags": tag_labels,
        "accepting_orders": bool(raw.get("accepting_orders")),
        "closed": closed,
        "enable_order_book": bool(raw.get("enable_order_book")),
        "best_bid": None if best_bid is None else float(best_bid),
        "best_ask": None if best_ask is None else float(best_ask),
        "mid_price": None if mid_price is None else float(mid_price),
        "last_trade_price": None if last_trade is None else float(last_trade),
        "volume": to_float(raw.get("volume")) or 0.0,
        "liquidity": to_float(raw.get("liquidity")) or 0.0,
        "source": "dexbuilder",
        "read_only": True,
    }


def _winning_outcome(
    prices: list[Decimal | None],
    symbols: list[str],
    closed: bool,
) -> tuple[int | None, str | None]:
    """Derive the resolved outcome from the upstream settlement prices.

    DexBuilder settles a closed market by pricing the winning outcome at
    exactly 1 and the losing outcome(s) at 0. A closed market with no (or more
    than one) outcome priced at 1 has not settled cleanly, so no winner is
    reported.
    """
    if not closed:
        return None, None
    winners = [index for index, price in enumerate(prices) if price == Decimal(1)]
    if len(winners) != 1:
        return None, None
    index = winners[0]
    symbol = symbols[index] if index < len(symbols) else None
    return index, symbol


def normalize_event(raw: dict) -> dict:
    """Upstream event -> Dolymarket event payload."""
    tags_raw = raw.get("tags") or []
    tags = sorted(
        {
            _label(t.get("label")) if isinstance(t, dict) else str(t)
            for t in tags_raw
            if t
        }
    )
    closed = bool(raw.get("closed"))
    active = bool(raw.get("active"))
    status = "CLOSED" if closed else ("ACTIVE" if active else "PENDING")
    return {
        "id": str(raw.get("event_id") or raw.get("id") or ""),
        "slug": raw.get("slug"),
        "title": _label(raw.get("title")),
        "description": None,
        "category": raw.get("category") or "",
        "tags": tags,
        "status": status,
        "start_date": _iso(raw.get("start_date")),
        "end_date": _iso(raw.get("end_date")),
        "total_volume": to_float(raw.get("volume")) or 0.0,
        "image": raw.get("image"),
        "icon": raw.get("icon"),
        "source": "dexbuilder",
        "read_only": True,
    }


def normalize_order_book(raw: dict, depth: int = 50) -> dict:
    """Upstream book -> Dolymarket snapshot (best price first on both sides)."""

    def levels(items: Any, best_first_high: bool) -> list[list]:
        collected: list[tuple[Decimal, Decimal]] = []
        for level in items or []:
            if not isinstance(level, dict):
                continue
            price = to_decimal(level.get("price"))
            size = to_decimal(level.get("size"))
            if price is None or size is None:
                continue
            collected.append((price, size))
        collected.sort(key=lambda pair: pair[0], reverse=best_first_high)
        return [[str(price.normalize()), float(size)] for price, size in collected[:depth]]

    return {
        "token_id": raw.get("token_id"),
        "bids": levels(raw.get("bids"), True),
        "asks": levels(raw.get("asks"), False),
        "timestamp": int(time.time() * 1000),
        "source": "dexbuilder",
    }


def normalize_trades(raw: Any) -> list[dict]:
    """Upstream trade tape -> Dolymarket trade list."""
    items = raw if isinstance(raw, list) else (raw or {}).get("items") or []
    trades: list[dict] = []
    for trade in items:
        if not isinstance(trade, dict):
            continue
        price = to_decimal(trade.get("price"))
        size = to_decimal(trade.get("size"))
        trades.append(
            {
                "id": str(trade.get("id") or ""),
                "market_id": str(trade.get("market_id") or ""),
                "token_id": str(trade.get("token_id") or ""),
                "outcome": trade.get("outcome"),
                "side": str(trade.get("side") or "").upper(),
                "price": None if price is None else float(price),
                "size": None if size is None else float(size),
                "timestamp": _iso(trade.get("created_at")),
                "created_at": trade.get("created_at"),
                "source": "dexbuilder",
            }
        )
    return trades


def normalize_candles(raw: Any) -> list[dict]:
    """Upstream OHLCV -> Dolymarket candle list."""
    items = raw if isinstance(raw, list) else (raw or {}).get("items") or []
    candles: list[dict] = []
    for candle in items:
        if not isinstance(candle, dict):
            continue
        candles.append(
            {
                "timestamp": int(to_decimal(candle.get("t")) or 0),
                "open": to_float(candle.get("o")),
                "high": to_float(candle.get("h")),
                "low": to_float(candle.get("l")),
                "close": to_float(candle.get("c")),
                "volume": to_float(candle.get("v")) or 0.0,
            }
        )
    return candles


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


class LiveMarketFeed:
    """Fetches, normalizes and caches live DexBuilder market data."""

    def __init__(
        self,
        client: DexBuilderClient | None = None,
        ttl: float = CACHE_TTL_SECONDS,
    ):
        self.client = client or DexBuilderClient()
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._failures = 0
        self._circuit_open_until = 0.0
        self._lock = asyncio.Lock()

    # -- infrastructure -----------------------------------------------------

    def reset(self) -> None:
        """Drop cached values and close the circuit (used by tests)."""
        self._cache.clear()
        self._failures = 0
        self._circuit_open_until = 0.0

    def status(self) -> dict:
        return {
            "upstream": self.client.config.DEXBUILDER_API_BASE,
            "public_reads": self.client.public_reads,
            "credentialed": self.client.enabled,
            "cache_entries": len(self._cache),
            "circuit_open": time.monotonic() < self._circuit_open_until,
            "consecutive_failures": self._failures,
        }

    async def _fetch(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        if now < self._circuit_open_until:
            raise LiveUnavailableError("DexBuilder upstream circuit is open")
        try:
            value = await factory()
        except Exception as exc:  # noqa: BLE001 - upstream may raise anything
            self._failures += 1
            if self._failures >= FAILURE_THRESHOLD:
                self._circuit_open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS
            if cached is not None:
                # Serve the stale value rather than failing the request.
                return cached[1]
            raise LiveUnavailableError(f"DexBuilder upstream unavailable: {exc}") from exc
        self._failures = 0
        self._cache[key] = (time.monotonic() + self.ttl, value)
        return value

    # -- surfaces -----------------------------------------------------------

    async def markets(
        self,
        status: str | None = "active",
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        upstream_status = normalize_status(status)
        params: dict[str, Any] = {"limit": limit}
        if upstream_status:
            params["status"] = upstream_status
        if category:
            params["category"] = category
        if offset:
            params["offset"] = offset
        key = f"markets:{upstream_status}:{category}:{limit}:{offset}"
        raw = await self._fetch(key, lambda: self.client.get_markets(**params))
        items = raw.get("items", []) if isinstance(raw, dict) else (raw or [])
        markets = [normalize_market(item) for item in items if isinstance(item, dict)]
        return {
            "markets": markets,
            "total": raw.get("total", len(markets)) if isinstance(raw, dict) else len(markets),
            "status": upstream_status or "closed",
            "offset": offset,
            "limit": limit,
            "has_more": len(markets) >= limit,
            "next_offset": offset + len(markets) if len(markets) >= limit else None,
            "source": "dexbuilder",
            "read_only": True,
        }

    async def market(self, market_id: str) -> dict:
        key = f"market:{market_id}"
        raw = await self._fetch(key, lambda: self.client.get_market(market_id))
        if not isinstance(raw, dict) or not raw:
            raise LiveUnavailableError(f"DexBuilder market {market_id} not found")
        return normalize_market(raw)

    async def events(self, limit: int = 50) -> dict:
        key = f"events:{limit}"
        raw = await self._fetch(key, lambda: self.client.get_events(limit=limit))
        items = raw.get("items", []) if isinstance(raw, dict) else (raw or [])
        events = [normalize_event(item) for item in items if isinstance(item, dict)]
        return {
            "events": events,
            "next_cursor": raw.get("next_cursor") if isinstance(raw, dict) else None,
            "source": "dexbuilder",
            "read_only": True,
        }

    async def tags(self) -> dict:
        raw = await self._fetch("tags", self.client.get_tags)
        return {"tags": normalize_tags(raw), "source": "dexbuilder"}

    async def time(self) -> dict:
        raw = await self._fetch("time", self.client.get_time)
        server_time = to_decimal(raw.get("server_time")) if isinstance(raw, dict) else None
        if server_time is None:
            server_time = Decimal(int(time.time() * 1000))
        return {"server_time": int(server_time), "source": "dexbuilder"}

    async def order_book(self, token_id: str, depth: int = 50) -> dict:
        key = f"book:{token_id}:{depth}"
        raw = await self._fetch(key, lambda: self.client.get_order_book(token_id))
        if not isinstance(raw, dict):
            raise LiveUnavailableError("DexBuilder returned an invalid order book")
        return normalize_order_book(raw, depth=depth)

    async def price_history(
        self,
        token_id: str,
        interval: str = "1h",
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> dict:
        now_ms = int(time.time() * 1000)
        if to_ms is None:
            to_ms = now_ms
        if from_ms is None:
            from_ms = to_ms - MAX_HISTORY_WINDOW_MS
        if to_ms - from_ms > MAX_HISTORY_WINDOW_MS:
            from_ms = to_ms - MAX_HISTORY_WINDOW_MS
        key = f"history:{token_id}:{interval}:{from_ms}:{to_ms}"

        async def factory() -> Any:
            try:
                raw = await self.client.get_price_history(
                    token_id, interval=interval, from_ms=from_ms, to_ms=to_ms
                )
                return raw
            except Exception:
                # Upstream `price_history` answers 404 ("token not found") for
                # tokens it does not index; the candlestick surface covers the
                # same window and is used as the fallback.
                return await self.client.get_candlesticks(
                    token_id,
                    interval=interval,
                    from_ms=from_ms,
                    to_ms=to_ms,
                    limit=500,
                )

        raw = await self._fetch(key, factory)
        items = raw if isinstance(raw, list) else (raw or {}).get("items") or []
        return {
            "token_id": token_id,
            "interval": interval,
            "from": from_ms,
            "to": to_ms,
            "candles": normalize_candles(items),
            "source": "dexbuilder",
        }

    async def candlesticks(
        self,
        token_id: str,
        interval: str = "1m",
        limit: int = 200,
    ) -> dict:
        key = f"candles:{token_id}:{interval}:{limit}"
        raw = await self._fetch(
            key,
            lambda: self.client.get_candlesticks(token_id, interval=interval, limit=limit),
        )
        items = raw if isinstance(raw, list) else (raw or {}).get("items") or []
        return {
            "token_id": token_id,
            "interval": interval,
            "candlesticks": normalize_candles(items),
            "source": "dexbuilder",
        }

    async def market_trades(self, market_id: str, limit: int = 50) -> dict:
        key = f"trades:{market_id}:{limit}"
        raw = await self._fetch(key, lambda: self.client.get_market_trades(market_id, limit=limit))
        return {"trades": normalize_trades(raw), "source": "dexbuilder"}


_feed: LiveMarketFeed | None = None


def get_live_feed() -> LiveMarketFeed:
    """Process-wide live feed singleton."""
    global _feed
    if _feed is None:
        _feed = LiveMarketFeed(DexBuilderClient(get_config()))
    return _feed
