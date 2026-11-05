"""DexBuilder credentialed access: signing scheme, rejection mapping, diagnostics.

The signing scheme follows the official DexBuilder authentication spec:

    METHOD + "\\n" + PATH + "\\n" + QUERY + "\\n"
    + HexEncode(SHA512(raw body)) + "\\n" + TIMESTAMP

    SIGN = HexEncode(HMAC_SHA512(api_secret, signed message))
"""
from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from app.services.dexbuilder import (
    DexBuilderAuthError,
    DexBuilderClient,
    DexBuilderConfig,
    canonical_signature_message,
    sign_payload,
)

pytestmark = pytest.mark.asyncio

#: SHA512 of an empty body, as published in the DexBuilder signing spec.
EMPTY_BODY_SHA512 = (
    "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47"
    "d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
)

API_KEY = "a" * 32
API_SECRET = "b" * 64


def make_config(**overrides) -> DexBuilderConfig:
    values = {
        "DEXBUILDER_API_BASE": "https://api.dexbuilder.com",
        "DEXBUILDER_API_KEY": API_KEY,
        "DEXBUILDER_API_SECRET": API_SECRET,
    }
    values.update(overrides)
    return DexBuilderConfig(**values)


def make_client(handler, **overrides) -> DexBuilderClient:
    transport = httpx.MockTransport(handler)
    return DexBuilderClient(make_config(**overrides), transport=transport)


async def test_canonical_message_matches_the_documented_example():
    message = canonical_signature_message(
        "GET",
        "/api/v1/dex_futures/usdt/orders",
        "status=finished&limit=50",
        "",
        "1541993715",
    )
    assert message == (
        "GET\n"
        "/api/v1/dex_futures/usdt/orders\n"
        "status=finished&limit=50\n"
        f"{EMPTY_BODY_SHA512}\n"
        "1541993715"
    )
    assert hashlib.sha512(b"").hexdigest() == EMPTY_BODY_SHA512


async def test_signature_is_hex_hmac_sha512_of_the_canonical_message():
    message = canonical_signature_message("GET", "/api/v4/prediction/usertrades", "", "", "1541993715")
    expected = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha512).hexdigest()
    assert sign_payload(API_SECRET, message) == expected
    assert len(expected) == 128


async def test_sign_headers_use_the_documented_names_only():
    client = make_client(lambda request: httpx.Response(200, json={}))
    headers = client._sign("GET", "/api/v4/prediction/usertrades", "", "", timestamp="1541993715")
    assert set(headers) == {"KEY", "Timestamp", "SIGN"}
    assert headers["KEY"] == API_KEY
    assert headers["Timestamp"] == "1541993715"
    assert headers["SIGN"] == sign_payload(
        API_SECRET,
        canonical_signature_message("GET", "/api/v4/prediction/usertrades", "", "", "1541993715"),
    )


async def test_public_read_without_a_secret_is_unsigned():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"items": []})

    client = make_client(handler, DEXBUILDER_API_SECRET="")
    await client.get_markets(limit=1)
    request = captured[0]
    assert "KEY" not in request.headers
    assert "Timestamp" not in request.headers
    assert "SIGN" not in request.headers


async def test_signed_query_is_byte_identical_to_the_sent_query():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    await client.get_markets(status="active", limit=10, offset=5)

    request = captured[0]
    sent_query = request.url.query.decode()
    assert sent_query == "status=active&limit=10&offset=5"

    # The signature must verify against what was actually sent.
    rebuilt = canonical_signature_message(
        request.method,
        request.url.path,
        sent_query,
        request.content.decode(),
        request.headers["Timestamp"],
    )
    assert sign_payload(API_SECRET, rebuilt) == request.headers["SIGN"]


async def test_upstream_401_raises_a_credential_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"label": "INVALID_KEY", "message": "Invalid key provided"})

    client = make_client(handler)
    with pytest.raises(DexBuilderAuthError) as excinfo:
        await client.get_user_trades()
    assert excinfo.value.label == "INVALID_KEY"
    assert excinfo.value.status_code == 401


async def test_credential_diagnostic_reports_the_upstream_label():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"label": "INVALID_KEY", "message": "Invalid key provided"})

    client = make_client(handler)
    result = await client.check_credentials()
    assert result["configured"] is True
    assert result["key_present"] is True
    assert result["secret_present"] is True
    assert result["scheme"] == "HMAC-SHA512"
    assert result["authenticated"] is False
    assert result["upstream"]["label"] == "INVALID_KEY"
    assert result["upstream"]["status"] == 401
    assert API_KEY not in str(result)
    assert API_SECRET not in str(result)


async def test_credential_diagnostic_without_a_secret():
    client = make_client(
        lambda request: httpx.Response(200, json={}),
        DEXBUILDER_API_KEY="",
        DEXBUILDER_API_SECRET="",
    )
    result = await client.check_credentials()
    assert result["configured"] is False
    assert result["upstream"]["label"] == "NOT_CONFIGURED"


async def test_credential_diagnostic_reports_success():
    client = make_client(lambda request: httpx.Response(200, json={"items": []}))
    result = await client.check_credentials()
    assert result["authenticated"] is True
    assert result["upstream"]["label"] == "OK"


async def test_proxy_maps_a_credential_error(client):
    from app.api.v4.dexbuilder import proxy

    class RejectingClient:
        enabled = True

        async def get_markets(self, **kwargs):
            raise DexBuilderAuthError("INVALID_KEY", 401, "Invalid key provided")

    app = client._transport.app
    app.dependency_overrides[proxy.get_client] = lambda: RejectingClient()
    try:
        response = await client.get("/api/v4/dexbuilder/markets")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert response.json()["detail"] == "DEXBUILDER_UPSTREAM_UNAUTHORIZED"
    assert response.headers["X-Upstream-Error"] == "INVALID_KEY"


async def test_proxy_keeps_the_generic_error_for_other_failures(client):
    from app.api.v4.dexbuilder import proxy

    class BrokenClient:
        enabled = True

        async def get_markets(self, **kwargs):
            raise RuntimeError("boom")

    app = client._transport.app
    app.dependency_overrides[proxy.get_client] = lambda: BrokenClient()
    try:
        response = await client.get("/api/v4/dexbuilder/markets")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert response.json()["detail"] == "DEXBUILDER_BAD_RESPONSE"


async def test_auth_route_never_leaks_the_credentials(client):
    from app.api.v4.prediction import live
    from app.services.live_data import LiveMarketFeed

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"label": "INVALID_KEY", "message": "Invalid key provided"})

    feed = LiveMarketFeed(make_client(handler))
    app = client._transport.app
    app.dependency_overrides[live.get_live_feed] = lambda: feed
    try:
        response = await client.get("/api/v4/prediction/live/auth")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["scheme"] == "HMAC-SHA512"
    assert body["authenticated"] is False
    assert body["upstream"]["label"] == "INVALID_KEY"
    assert API_KEY not in response.text
    assert API_SECRET not in response.text
