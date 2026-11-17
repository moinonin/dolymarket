"""Live BTC Fear & Greed endpoints backed by Gate.io WebSocket + REST."""
from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.services.fear_greed import PROFILE_WEIGHTS, fear_greed_service

router = APIRouter(tags=["feargreed"])


@router.get("/api/v1/feargreed/latest")
async def get_latest_fear_greed(
    profile: str = Query(default="microstructure"),
):
    if profile not in PROFILE_WEIGHTS:
        profile = "microstructure"
    return await fear_greed_service.get_latest(profile=profile)


@router.websocket("/ws/feargreed")
async def ws_fear_greed(
    ws: WebSocket,
    profile: str = Query(default="microstructure"),
):
    if profile not in PROFILE_WEIGHTS:
        profile = "microstructure"
    await ws.accept()
    await fear_greed_service.register(ws, profile)
    try:
        initial = await fear_greed_service.get_latest(profile=profile)
        await ws.send_json(initial)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        fear_greed_service.unregister(ws, profile)
