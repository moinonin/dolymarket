"""Upstream DexBuilder websocket protocol and its translation to the local envelope.

The upstream broker (``wss://broker.dexbuilder.com/ws/dex-builder/prediction``)
speaks its own request/response envelope::

    subscribe  {"t": 1720000000123, "id": "req-1", "op": "subscribe",
                "ch": "pred.depth",
                "payload": {"items": [{"token_id": "...", "level": 20}]}}
    ack        {"t": ..., "id": ..., "op": "subscribe", "ch": ...,
                "err": null, "result": {"status": "success"}}
    data       {"t": ..., "trace_id": ..., "type": "snapshot"|"update",
                "ch": ..., "err": null, "result": {...}}

Dolymarket's own websocket protocol is different (``{"action": "subscribe",
"channel": ..., "token_id": ...}`` in, ``{"channel": ...}`` out). This module
translates between the two: the browser keeps speaking the local envelope and
the server owns the upstream protocol.

Numbers are parsed with :class:`~decimal.Decimal` and only converted to
``float`` at the JSON boundary, mirroring the rest of the live-data code.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets

from app.ws.sequence import next_stream_sequence

CHANNEL_DEPTH = "pred.depth"
CHANNEL_BBO = "pred.bbo"
CHANNEL_TRADES = "pred.trades"
CHANNEL_STATUS = "pred.status"

#: Channels the bridge forwards, mapped to the upstream subscription key.
CHANNEL_KEYS: dict[str, str] = {
    CHANNEL_DEPTH: "token_id",
    CHANNEL_BBO: "token_id",
    CHANNEL_TRADES: "condition_id",
    CHANNEL_STATUS: "market_id",
}

#: Depth levels the upstream broker accepts.
DEPTH_LEVELS = (5, 10, 20, 50)
DEFAULT_DEPTH_LEVEL = 20

#: Reconnect backoff for the upstream connection.
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0

#: Upper bound of active subscriptions per browser session.
MAX_ACTIVE_SUBSCRIPTIONS = 200

#: Error frame sent to the browser when the upstream cannot be reached.
UPSTREAM_UNAVAILABLE = "DEXBUILDER_UPSTREAM_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Numeric helpers (Decimal first, JSON boundary last)
# ---------------------------------------------------------------------------


def to_decimal(value: Any) -> Decimal | None:
    """Parse an upstream numeric (often a string) into a Decimal."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def to_float(value: Any) -> float | None:
    """Serialize a Decimal (or upstream numeric) for JSON output."""
    parsed = to_decimal(value)
    return None if parsed is None else float(parsed)


def price_string(value: Any) -> str | None:
    """Normalize a price into the plain string form used by the local book."""
    parsed = to_decimal(value)
    if parsed is None:
        return None
    return format(parsed.normalize(), "f")


def _levels(raw: Any) -> list[list[Any]]:
    """Normalize upstream ``[[price, size], ...]`` levels.

    The local order-book snapshot publishes ``[price string, size number]``;
    the upstream sends both as strings, so the size is converted at the JSON
    boundary.
    """
    out: list[list[Any]] = []
    for level in raw or []:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = price_string(level[0])
        size = to_float(level[1])
        if price is None or size is None:
            continue
        out.append([price, size])
    return out


def _timestamp_ms(result: Mapping[str, Any]) -> int:
    """Upstream timestamps are unix milliseconds unless stated otherwise."""
    parsed = to_decimal(result.get("ts"))
    if parsed is None:
        return int(time.time() * 1000)
    return int(parsed)


# ---------------------------------------------------------------------------
# Upstream request construction
# ---------------------------------------------------------------------------


def subscription_item(channel: str, message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build the upstream subscription item for a browser message.

    The browser speaks the local envelope (``channel`` plus the identifying
    field); the upstream wants a channel-specific item.
    """
    key = CHANNEL_KEYS.get(channel)
    if key is None:
        return None
    value = message.get(key)
    if not value:
        return None
    if channel == CHANNEL_DEPTH:
        level = message.get("level")
        try:
            level = int(level) if level is not None else DEFAULT_DEPTH_LEVEL
        except (TypeError, ValueError):
            level = DEFAULT_DEPTH_LEVEL
        if level not in DEPTH_LEVELS:
            level = DEFAULT_DEPTH_LEVEL
        return {"token_id": str(value), "level": level}
    return {key: str(value)}


def build_subscribe_request(
    channel: str,
    item: Mapping[str, Any],
    request_id: str,
    timestamp_ms: int | None = None,
    op: str = "subscribe",
) -> dict[str, Any]:
    """Build an upstream subscribe/unsubscribe request.

    The upstream expects the request timestamp in unix **milliseconds** and
    rejects a request that is more than 60 seconds away from its clock.
    """
    stamp = int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms)
    return {
        "t": stamp,
        "id": request_id,
        "op": op,
        "ch": channel,
        "payload": {"items": [dict(item)]},
    }


# ---------------------------------------------------------------------------
# Upstream -> local translation
# ---------------------------------------------------------------------------


def _error_parts(error: Any) -> tuple[Any, str]:
    if isinstance(error, Mapping):
        return error.get("code"), str(error.get("msg") or "upstream error")
    return None, str(error)


def _depth(result: Mapping[str, Any]) -> dict[str, Any]:
    sequence = next_stream_sequence()
    return {
        "channel": CHANNEL_DEPTH,
        "token_id": str(result.get("token_id") or ""),
        "bids": _levels(result.get("bids")),
        "asks": _levels(result.get("asks")),
        "sequence": sequence,
        "stream_sequence": sequence,
        "timestamp": _timestamp_ms(result),
    }


def _bbo(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "channel": CHANNEL_BBO,
        "token_id": str(result.get("token_id") or ""),
        "bid_price": to_float(result.get("bid_px")),
        "ask_price": to_float(result.get("ask_px")),
        "last_price": to_float(result.get("last_px")),
        "timestamp": _timestamp_ms(result),
        "stream_sequence": next_stream_sequence(),
    }


def _iso_ms(value: Any) -> str | None:
    """Upstream millisecond timestamp -> ISO-8601 string."""
    parsed = to_decimal(value)
    if parsed is None:
        return None
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(float(parsed) / 1000, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _trades(result: Mapping[str, Any]) -> dict[str, Any]:
    """Upstream trade -> the same shape the REST trade tape publishes."""
    timestamp_ms = _timestamp_ms(result)
    condition_id = result.get("condition_id")
    token_id = result.get("token_id")
    size = to_float(result.get("qty"))
    return {
        "channel": CHANNEL_TRADES,
        "id": f"{timestamp_ms}-{token_id or condition_id}",
        "market_id": result.get("market_id") or condition_id or "",
        "condition_id": condition_id,
        "token_id": token_id,
        "outcome": result.get("outcome"),
        "side": str(result.get("side") or "").upper(),
        "price": to_float(result.get("px")),
        "size": size,
        "shares": size,
        "timestamp": _iso_ms(result.get("ts")),
        "source": "dexbuilder",
        "stream_sequence": next_stream_sequence(),
    }


def _status(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "channel": CHANNEL_STATUS,
        "market_id": result.get("market_id"),
        "condition_id": result.get("condition_id"),
        "status": result.get("status"),
        "closed": bool(result.get("closed")),
        "accepting_orders": bool(result.get("accepting_orders")),
        "timestamp": _timestamp_ms(result),
        "stream_sequence": next_stream_sequence(),
    }


_TRANSLATORS = {
    CHANNEL_DEPTH: _depth,
    CHANNEL_BBO: _bbo,
    CHANNEL_TRADES: _trades,
    CHANNEL_STATUS: _status,
}


def translate_message(message: Any) -> list[dict[str, Any]]:
    """Translate one upstream frame into zero or more local-envelope frames.

    Acknowledgements carry no market data and are dropped; upstream errors are
    forwarded as an error frame on the same channel.
    """
    if not isinstance(message, Mapping):
        return []
    channel = str(message.get("ch") or "")
    error = message.get("err")
    if error:
        code, text = _error_parts(error)
        return [{"channel": channel, "error": text, "error_code": code}]
    if message.get("type") not in ("snapshot", "update"):
        return []
    result = message.get("result")
    if not isinstance(result, Mapping):
        return []
    translator = _TRANSLATORS.get(channel)
    if translator is None:
        return []
    return [translator(result)]


# ---------------------------------------------------------------------------
# Upstream session
# ---------------------------------------------------------------------------


class DexBuilderStreamSession:
    """One upstream broker connection serving one browser socket.

    The session reconnects with exponential backoff and replays the active
    subscriptions, so a broker outage degrades the stream instead of breaking
    the page.
    """

    def __init__(
        self,
        url: str,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        reconnect_min: float = RECONNECT_MIN_SECONDS,
        reconnect_max: float = RECONNECT_MAX_SECONDS,
    ) -> None:
        self._url = url
        self._send = send
        self._reconnect_min = reconnect_min
        self._reconnect_max = reconnect_max
        self._ws: Any = None
        self._task: asyncio.Task | None = None
        self._counter = 0
        self._closed = False
        self._requests: dict[str, dict[str, Any]] = {}
        self._sent: set[str] = set()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def start(self) -> None:
        """Start the background supervisor (never blocks the caller)."""
        if self._task is None and not self._closed:
            self._task = asyncio.create_task(self._supervise())

    async def subscribe(self, channel: str, item: Mapping[str, Any]) -> None:
        """Register a subscription and push it upstream when connected."""
        self._counter += 1
        request = build_subscribe_request(channel, item, f"dm-{self._counter}")
        if len(self._requests) >= MAX_ACTIVE_SUBSCRIPTIONS:
            oldest = next(iter(self._requests))
            self._requests.pop(oldest, None)
        self._requests[request["id"]] = request
        await self._write(request)

    async def unsubscribe(self, channel: str, item: Mapping[str, Any]) -> None:
        """Remove a subscription upstream."""
        self._counter += 1
        request = build_subscribe_request(
            channel, item, f"dm-{self._counter}", op="unsubscribe"
        )
        await self._write(request)

    async def close(self) -> None:
        """Close the session and stop the supervisor."""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
            self._task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    # -- internals -----------------------------------------------------------

    async def _write(self, request: Mapping[str, Any]) -> None:
        if self._ws is None:
            return
        request_id = str(request.get("id"))
        if request_id in self._sent:
            return
        try:
            await self._ws.send(json.dumps(request))
        except Exception:  # noqa: BLE001 - the supervisor reconnects
            self._ws = None
            return
        self._sent.add(request_id)

    async def _supervise(self) -> None:
        attempt = 0
        while not self._closed:
            try:
                self._ws = await websockets.connect(
                    self._url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                )
            except Exception:  # noqa: BLE001 - any failure is an outage
                self._ws = None
                await self._send({"action": "error", "detail": UPSTREAM_UNAVAILABLE})
                await asyncio.sleep(self._backoff(attempt))
                attempt += 1
                continue

            attempt = 0
            # A fresh connection replays every active subscription.
            self._sent.clear()
            for request in self._requests.values():
                await self._write(request)
            try:
                async for raw in self._ws:
                    self._dispatch(raw)
            except Exception:  # noqa: BLE001 - the connection dropped
                pass
            finally:
                if self._ws is not None:
                    try:
                        await self._ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._ws = None
            if self._closed:
                return
            await self._send({"action": "error", "detail": UPSTREAM_UNAVAILABLE})
            await asyncio.sleep(self._backoff(attempt))
            attempt += 1

    def _backoff(self, attempt: int) -> float:
        delay = min(self._reconnect_max, self._reconnect_min * (2**attempt))
        return delay * random.uniform(0.9, 1.1)

    def _dispatch(self, raw: Any) -> None:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return
        for message in translate_message(payload):
            self._spawn(self._send(message))

    @staticmethod
    def _spawn(coro: Awaitable[None]) -> None:
        task = asyncio.create_task(coro)  # type: ignore[arg-type]
        task.add_done_callback(_swallow_exception)


def _swallow_exception(task: asyncio.Task) -> None:
    """Ignore delivery failures (a closed browser socket is not an error)."""
    if task.cancelled():
        return
    task.exception()
