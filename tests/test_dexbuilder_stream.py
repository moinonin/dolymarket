"""Upstream DexBuilder websocket bridge: protocol, translation, degradation.

The tests run against a local fake broker that speaks the upstream envelope,
so nothing depends on the (currently unreachable) DexBuilder infrastructure.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
import websockets
from fastapi import WebSocketDisconnect

from app.api.v4 import ws_live
from app.services.dexbuilder import DexBuilderConfig
from app.ws.dexbuilder_stream import (
    DexBuilderStreamSession,
    build_subscribe_request,
    subscription_item,
    translate_message,
)

pytestmark = pytest.mark.anyio


class FakeBroker:
    """A local websocket server that speaks the upstream DexBuilder envelope."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._server = None

    async def start(self) -> str:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, websocket) -> None:
        async for raw in websocket:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            self.requests.append(message)
            await websocket.send(
                json.dumps(
                    {
                        "t": message.get("t"),
                        "id": message.get("id"),
                        "trace_id": "trace-1",
                        "op": message.get("op"),
                        "ch": message.get("ch"),
                        "err": None,
                        "result": {"status": "success"},
                    }
                )
            )
            items = (message.get("payload") or {}).get("items") or [{}]
            item = items[0]
            if message.get("ch") == "pred.depth":
                await websocket.send(
                    json.dumps(
                        {
                            "t": 1720000000124,
                            "trace_id": "trace-1",
                            "type": "snapshot",
                            "ch": "pred.depth",
                            "err": None,
                            "result": {
                                "token_id": item.get("token_id"),
                                "level": item.get("level"),
                                "full": True,
                                "bids": [["0.44", "100"]],
                                "asks": [["0.46", "80"]],
                                "hash": "book-hash",
                                "ts": 1720000000123,
                            },
                        }
                    )
                )


class StubWebSocket:
    """Minimal websocket double for driving the route."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self.incoming = list(incoming or [])
        self.sent: list[dict] = []
        self.accepted = False
        self._disconnect = asyncio.Event()

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        await self._disconnect.wait()
        raise WebSocketDisconnect()

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def disconnect(self) -> None:
        self._disconnect.set()


async def _wait_for(predicate, attempts: int = 300) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_subscribe_request_uses_the_documented_envelope():
    request = build_subscribe_request(
        "pred.depth",
        {"token_id": "tok-1", "level": 20},
        "dm-1",
        timestamp_ms=1720000000123,
    )
    assert request == {
        "t": 1720000000123,
        "id": "dm-1",
        "op": "subscribe",
        "ch": "pred.depth",
        "payload": {"items": [{"token_id": "tok-1", "level": 20}]},
    }


def test_subscribe_request_ids_are_unique():
    first = build_subscribe_request("pred.bbo", {"token_id": "t"}, "dm-1")
    second = build_subscribe_request("pred.bbo", {"token_id": "t"}, "dm-2")
    assert first["id"] != second["id"]


def test_subscription_item_maps_the_local_envelope():
    assert subscription_item("pred.depth", {"token_id": "t1"}) == {
        "token_id": "t1",
        "level": 20,
    }
    # An unsupported level falls back to the default depth.
    assert subscription_item("pred.depth", {"token_id": "t1", "level": 99})["level"] == 20
    assert subscription_item("pred.bbo", {"token_id": "t1"}) == {"token_id": "t1"}
    assert subscription_item("pred.trades", {"condition_id": "c1"}) == {"condition_id": "c1"}
    assert subscription_item("pred.status", {"market_id": "m1"}) == {"market_id": "m1"}
    assert subscription_item("pred.unknown", {"token_id": "t1"}) is None
    assert subscription_item("pred.depth", {}) is None


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def test_translate_depth_keeps_the_local_book_shape():
    frames = translate_message(
        {
            "t": 1720000000124,
            "type": "snapshot",
            "ch": "pred.depth",
            "err": None,
            "result": {
                "token_id": "tok-1",
                "level": 20,
                "full": True,
                "bids": [["0.44", "100"]],
                "asks": [["0.46", "80"]],
                "ts": 1720000000123,
            },
        }
    )
    assert len(frames) == 1
    frame = frames[0]
    assert frame["channel"] == "pred.depth"
    assert frame["token_id"] == "tok-1"
    assert frame["bids"] == [["0.44", 100.0]]
    assert frame["asks"] == [["0.46", 80.0]]
    assert frame["timestamp"] == 1720000000123
    assert frame["stream_sequence"] > 0


def test_translate_bbo_and_trades():
    bbo = translate_message(
        {
            "type": "update",
            "ch": "pred.bbo",
            "err": None,
            "result": {
                "condition_id": "c1",
                "token_id": "tok-1",
                "bid_px": "0.44",
                "ask_px": "0.46",
                "last_px": "0.45",
                "ts": 1720000000123,
            },
        }
    )[0]
    assert bbo["channel"] == "pred.bbo"
    assert bbo["bid_price"] == 0.44
    assert bbo["ask_price"] == 0.46
    assert bbo["last_price"] == 0.45

    trade = translate_message(
        {
            "type": "update",
            "ch": "pred.trades",
            "err": None,
            "result": {
                "condition_id": "c1",
                "token_id": "tok-1",
                "outcome": "Yes",
                "side": "buy",
                "px": "0.45",
                "qty": "10",
                "ts": 1720000000123,
            },
        }
    )[0]
    assert trade["channel"] == "pred.trades"
    assert trade["price"] == 0.45
    assert trade["size"] == 10.0
    assert trade["side"] == "BUY"
    assert trade["token_id"] == "tok-1"
    assert trade["timestamp"].startswith("2024-")


def test_translate_status():
    frame = translate_message(
        {
            "type": "update",
            "ch": "pred.status",
            "err": None,
            "result": {
                "market_id": "m1",
                "condition_id": "c1",
                "status": "ACTIVE",
                "closed": False,
                "accepting_orders": True,
                "ts": 1720000000123,
            },
        }
    )[0]
    assert frame["channel"] == "pred.status"
    assert frame["market_id"] == "m1"
    assert frame["status"] == "ACTIVE"
    assert frame["closed"] is False


def test_acknowledgements_are_dropped_and_errors_are_forwarded():
    assert (
        translate_message(
            {
                "op": "subscribe",
                "ch": "pred.depth",
                "err": None,
                "result": {"status": "success"},
            }
        )
        == []
    )
    frames = translate_message(
        {
            "op": "subscribe",
            "ch": "pred.depth",
            "err": {"code": 2, "msg": "invalid depth item"},
        }
    )
    assert frames == [
        {"channel": "pred.depth", "error": "invalid depth item", "error_code": 2}
    ]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


async def test_session_subscribes_upstream_and_translates_the_depth():
    broker = FakeBroker()
    url = await broker.start()
    received: list[dict] = []

    async def send(payload: dict) -> None:
        received.append(payload)

    session = DexBuilderStreamSession(url, send)
    session.start()
    try:
        await session.subscribe("pred.depth", {"token_id": "tok-1", "level": 20})
        await _wait_for(lambda: any(m.get("channel") == "pred.depth" for m in received))

        depth = next(m for m in received if m.get("channel") == "pred.depth")
        assert depth["token_id"] == "tok-1"
        assert depth["bids"] == [["0.44", 100.0]]
        assert depth["asks"] == [["0.46", 80.0]]

        request = broker.requests[0]
        assert request["op"] == "subscribe"
        assert request["ch"] == "pred.depth"
        assert request["payload"]["items"] == [{"token_id": "tok-1", "level": 20}]
        # The upstream expects unix milliseconds, not seconds.
        assert abs(request["t"] / 1000 - time.time()) < 60
    finally:
        await session.close()
        await broker.stop()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


async def test_route_bridges_the_browser_to_the_upstream(monkeypatch):
    broker = FakeBroker()
    url = await broker.start()
    monkeypatch.setattr(
        ws_live, "get_config", lambda: DexBuilderConfig(DEXBUILDER_WS_URL=url)
    )

    stub = StubWebSocket(
        [
            json.dumps(
                {"action": "subscribe", "channel": "pred.depth", "token_id": "tok-1"}
            )
        ]
    )
    task = asyncio.create_task(ws_live.live_ws(stub))
    try:
        await _wait_for(
            lambda: any(m.get("channel") == "pred.depth" for m in stub.sent)
        )
        assert stub.accepted is True
        depth = next(m for m in stub.sent if m.get("channel") == "pred.depth")
        assert depth["token_id"] == "tok-1"
        assert depth["bids"] == [["0.44", 100.0]]
    finally:
        stub.disconnect()
        await task
        await broker.stop()


async def test_route_answers_ping_with_pong(monkeypatch):
    monkeypatch.setattr(
        ws_live,
        "get_config",
        lambda: DexBuilderConfig(DEXBUILDER_WS_URL="ws://127.0.0.1:1"),
    )
    stub = StubWebSocket([json.dumps({"action": "ping"})])
    task = asyncio.create_task(ws_live.live_ws(stub))
    try:
        await _wait_for(lambda: any(m.get("action") == "pong" for m in stub.sent))
        assert {"action": "pong"} in stub.sent
    finally:
        stub.disconnect()
        await task


async def test_route_reports_an_unreachable_upstream(monkeypatch):
    monkeypatch.setattr(
        ws_live,
        "get_config",
        lambda: DexBuilderConfig(DEXBUILDER_WS_URL="ws://127.0.0.1:1"),
    )
    stub = StubWebSocket([])
    task = asyncio.create_task(ws_live.live_ws(stub))
    try:
        await _wait_for(lambda: bool(stub.sent))
        assert stub.sent[0] == {
            "action": "error",
            "detail": "DEXBUILDER_UPSTREAM_UNAVAILABLE",
        }
    finally:
        stub.disconnect()
        await task
