"""Real-time WebSocket channels (public depth/bbo/trades + private fills)."""
import asyncio
import json
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core import security
from app.engine.clob import OrderBook
from app.models.domain import User
from app.ws.manager import manager

router = APIRouter(tags=["websocket"])


def _origin_allowed(ws: WebSocket) -> bool:
    """Reject browser cross-site WebSocket hijacking.

    Browsers always send an ``Origin`` header and do not apply CORS to
    WebSockets, so an allowlist is enforced here. Native clients (no Origin
    header) are allowed. An origin whose host matches the request Host is
    accepted; extra deployments add entries to ``WS_ALLOWED_ORIGINS``.
    """
    headers = getattr(ws, "headers", None) or {}
    try:
        origin = headers.get("origin")
        host = headers.get("host")
    except AttributeError:
        origin = None
        host = None
    if not origin:
        return True
    allowed = {
        o.strip()
        for o in os.environ.get("WS_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    }
    if host:
        allowed.update({f"http://{host}", f"https://{host}"})
    return origin in allowed


async def _user_exists(user_id: str) -> bool:
    """Confirm the JWT subject still refers to a live account."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User.id).where(User.id == user_id))
        ).scalar_one_or_none() is not None


@router.websocket("/api/v4/prediction/ws/public")
async def public_ws(ws: WebSocket):
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
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
async def private_ws(ws: WebSocket, token: str | None = None, ticket: str | None = None):
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
    user_id: str | None = None
    try:
        # Authenticate via single-use ticket, query token, or bounded-timeout auth frame.
        if ticket:
            user_id = security.consume_ws_ticket(ticket)
            if not user_id or not await _user_exists(user_id):
                await ws.close(code=4401)
                return
        elif token:
            try:
                user_id = security.decode_access_token(token).get("sub")
            except Exception:
                await ws.close(code=4401)
                return
            if not user_id or not await _user_exists(user_id):
                await ws.close(code=4401)
                return
        else:
            await ws.accept()
            try:
                while user_id is None:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("action") == "ping":
                        await manager.send_json(ws, {"action": "pong"})
                    elif msg.get("action") == "auth":
                        if msg.get("ticket"):
                            user_id = security.consume_ws_ticket(msg.get("ticket"))
                        else:
                            tok = msg.get("token")
                            try:
                                user_id = security.decode_access_token(tok).get("sub")
                            except Exception:
                                await ws.close(code=4401)
                                return
                        if not user_id or not await _user_exists(user_id):
                            user_id = None
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
