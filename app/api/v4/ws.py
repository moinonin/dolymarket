"""Real-time WebSocket channels (public depth/bbo/trades + private fills)."""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import security
from app.engine.clob import OrderBook
from app.ws.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/api/v4/prediction/ws/public")
async def public_ws(ws: WebSocket):
    await manager.connect_public(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action")
            channel = msg.get("channel")
            if action == "subscribe":
                if channel in ("pred.depth", "pred.bbo", "pred.book_delta"):
                    token_id = msg.get("token_id")
                    if token_id:
                        manager.subscribe(ws, token_id)
                        # Initial depth snapshot upon subscribe.
                        from app.db.session import AsyncSessionLocal

                        async with AsyncSessionLocal() as session:
                            book = OrderBook(session, token_id)
                            record = {"channel": "pred.depth", **await book.snapshot()}
                        await manager.send_json(ws, record)
                elif channel in ("pred.trades", "pred.status", "pred.candlestick"):
                    manager.subscribe(ws, channel)
            elif action in ("resync", "snapshot"):
                # Catch-up request after a detected sequence gap or reconnect.
                token_id = msg.get("token_id")
                if token_id:
                    from app.db.session import AsyncSessionLocal

                    async with AsyncSessionLocal() as session:
                        book = OrderBook(session, token_id)
                        record = {"channel": "pred.depth", **await book.snapshot()}
                    await manager.send_json(ws, record)
            elif action == "ping":
                await manager.send_json(ws, {"action": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)


@router.websocket("/api/v4/prediction/ws/private")
async def private_ws(ws: WebSocket, token: str | None = None):
    user_id: str | None = None
    try:
        # Authenticate via query param or first auth action message.
        if token:
            try:
                user_id = security.decode_access_token(token).get("sub")
            except Exception:
                await ws.close(code=4401)
                return
        else:
            await ws.accept()
            try:
                while user_id is None:
                    raw = await ws.receive_text()
                    msg = json.loads(raw)
                    if msg.get("action") == "ping":
                        await manager.send_json(ws, {"action": "pong"})
                    elif msg.get("action") == "auth":
                        tok = msg.get("token")
                        try:
                            user_id = security.decode_access_token(tok).get("sub")
                        except Exception:
                            await ws.close(code=4401)
                            return
            except Exception:
                await ws.close(code=4401)
                return
        await manager.connect_private(ws, user_id)
        await manager.send_json(
            ws, {"channel": "pred.orders", "status": "SUBSCRIBED", "user_id": user_id}
        )
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("action") == "ping":
                await manager.send_json(ws, {"action": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
