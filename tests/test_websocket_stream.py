"""WebSocket streaming verification."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient


@pytest.fixture
def app():
    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def ws_client(app):
    with TestClient(app) as tc:
        yield tc


async def _register(email: str) -> str:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "StrongPass123"},
        )
        return resp.json()["access_token"]


@pytest.mark.anyio
async def test_websocket_public_ping_and_subscribe(ws_client):
    with ws_client.websocket_connect("/api/v4/prediction/ws/public") as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"action": "pong"}
        # Subscribe to a channel without token_id -> no snapshot is sent
        ws.send_json({"action": "subscribe", "channel": "pred.trades"})


@pytest.mark.anyio
async def test_websocket_private_rejects_bad_auth(ws_client):
    # Missing token AND closing on first invalid auth action.
    with pytest.raises(Exception), ws_client.websocket_connect(
        "/api/v4/prediction/ws/private?token=invalid.token"
    ) as wsclient:
        wsclient.receive_json()


@pytest.mark.anyio
async def test_websocket_private_authenticated(ws_client):
    token = await _register("ws-user@example.com")
    with ws_client.websocket_connect(
        f"/api/v4/prediction/ws/private?token={token}"
    ) as ws:
        msg = ws.receive_json()
        assert msg["status"] == "SUBSCRIBED"
