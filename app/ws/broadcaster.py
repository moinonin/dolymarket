"""Bridge between the matching engine and WebSocket channels."""
from app.ws.manager import manager


async def broadcast_engine_events(events: list[dict]) -> None:
    """Route engine events to public/private channels."""
    for event in events:
        channel = event.get("channel")
        user_id = event.pop("user_id", None)
        if channel in ("pred.trades",):
            await manager.broadcast(event)
        elif channel == "pred.orders":
            if user_id:
                manager.notify_user(user_id, event)
        elif channel == "pred.usertrades":
            for uid in (event.get("maker_user_id"), event.get("taker_user_id")):
                if uid:
                    manager.notify_user(uid, event)
        elif channel == "pred.positions":
            if user_id:
                manager.notify_user(user_id, event)
        else:
            await manager.broadcast(event)
