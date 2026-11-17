"""WebSocket connection manager with pub/sub channels."""
import asyncio
import json
from typing import Any

from starlette.websockets import WebSocketState


MAX_PUBLIC_CONNECTIONS = 1000
MAX_PRIVATE_PER_USER = 10
SEND_TIMEOUT_SECONDS = 2.0


class ConnectionManager:
    def __init__(self):
        self.public: list[Any] = []          # websocket objects
        self.private: dict[Any, str] = {}    # websocket -> user_id
        self.subscriptions: dict[Any, str] = {}  # websocket -> token_id (depth/bbo)
        self._loop_lock = asyncio.Lock()

    async def connect_public(self, ws) -> None:
        if len(self.public) >= MAX_PUBLIC_CONNECTIONS:
            await ws.close(code=4429)
            return
        if ws.client_state == WebSocketState.CONNECTING:
            await ws.accept()
        self.public.append(ws)

    async def connect_private(self, ws, user_id: str) -> None:
        user_sockets = [sock for sock, uid in self.private.items() if uid == user_id]
        if len(user_sockets) >= MAX_PRIVATE_PER_USER:
            self.disconnect(user_sockets[0])
        if ws.client_state == WebSocketState.CONNECTING:
            await ws.accept()
        self.private[ws] = user_id

    def disconnect(self, ws) -> None:
        if ws in self.public:
            self.public.remove(ws)
        self.private.pop(ws, None)
        self.subscriptions.pop(ws, None)

    def subscribe(self, ws, token_id: str) -> None:
        self.subscriptions[ws] = token_id

    async def send_json(self, ws, payload: dict) -> None:
        try:
            await asyncio.wait_for(
                ws.send_text(json.dumps(payload, default=str)),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            self.disconnect(ws)

    async def broadcast(self, payload: dict, filter_user_id: str | None = None) -> None:
        """Public broadcast; when ``filter_user_id`` set, only private sockets of that user."""
        if filter_user_id is not None:
            targets = [
                ws for ws, uid in self.private.items() if uid == filter_user_id
            ]
        else:
            targets = list(self.public)
        if targets:
            await asyncio.gather(
                *(self.send_json(ws, payload) for ws in targets),
                return_exceptions=True,
            )

    def notify(self, payload: dict) -> None:
        """Fire-and-forget broadcast from sync context (engine callbacks)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(payload))
        except RuntimeError:
            pass

    def notify_user(self, user_id: str, payload: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(payload, filter_user_id=user_id))
        except RuntimeError:
            pass


manager = ConnectionManager()
