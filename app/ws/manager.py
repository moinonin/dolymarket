"""WebSocket connection manager with pub/sub channels."""
import asyncio
import json
from typing import Any


class ConnectionManager:
    def __init__(self):
        self.public: list[Any] = []          # websocket objects
        self.private: dict[Any, str] = {}    # websocket -> user_id
        self.subscriptions: dict[Any, str] = {}  # websocket -> token_id (depth/bbo)
        self._loop_lock = asyncio.Lock()

    async def connect_public(self, ws) -> None:
        await ws.accept()
        self.public.append(ws)

    async def connect_private(self, ws, user_id: str) -> None:
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
            await ws.send_text(json.dumps(payload, default=str))
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
        for ws in targets:
            await self.send_json(ws, payload)

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
