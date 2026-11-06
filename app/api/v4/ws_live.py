"""Live upstream websocket bridge: browser <-> DexBuilder broker.

The browser speaks the Dolymarket envelope (``{"action": "subscribe",
"channel": ..., "token_id": ...}`` in, ``{"channel": ...}`` out); the server
owns the upstream DexBuilder protocol and translates every frame. Public
upstream channels need no credentials.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.dexbuilder import get_config
from app.ws.dexbuilder_stream import DexBuilderStreamSession, subscription_item

router = APIRouter(tags=["websocket"])


def _sender(ws: WebSocket) -> Callable[[dict], Awaitable[None]]:
    """Build the frame sender for a browser socket."""

    async def send(payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload, default=str))
        except Exception:  # noqa: BLE001 - the browser may be gone
            pass

    return send


@router.websocket("/api/v4/prediction/live/ws")
async def live_ws(ws: WebSocket) -> None:
    """Forward the browser's live subscriptions to the upstream broker."""
    await ws.accept()
    session = DexBuilderStreamSession(get_config().DEXBUILDER_WS_URL, _sender(ws))
    session.start()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(message, dict):
                continue
            action = message.get("action")
            if action in ("subscribe", "unsubscribe"):
                channel = str(message.get("channel") or "")
                item = subscription_item(channel, message)
                if item is None:
                    continue
                if action == "subscribe":
                    await session.subscribe(channel, item)
                else:
                    await session.unsubscribe(channel, item)
            elif action == "ping":
                await ws.send_text(json.dumps({"action": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
