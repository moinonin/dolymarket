"""Bridge between the matching engine and WebSocket channels."""
from app.ws.manager import manager
from app.ws.sequence import next_stream_sequence


async def broadcast_engine_events(events: list[dict]) -> None:
    """Route engine events to public/private channels.

    Public messages receive a contiguous ``stream_sequence`` so clients can
    detect dropped packets and request a snapshot catch-up.
    """
    for event in events:
        channel = event.get("channel")
        user_id = event.pop("user_id", None)
        if channel in ("pred.trades", "pred.depth", "pred.bbo", "pred.book_delta"):
            event["stream_sequence"] = next_stream_sequence()
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
        elif channel == "pred.status":
            event["stream_sequence"] = next_stream_sequence()
            await manager.broadcast(event)
        else:
            await manager.broadcast(event)
