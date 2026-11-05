"""Live DexBuilder data: normalizers, cache/circuit behaviour and HTTP surfaces."""
from __future__ import annotations

import httpx
import pytest

from app.api.v4.prediction.live import get_live_feed
from app.services.dexbuilder import DexBuilderClient, DexBuilderConfig
from app.services.live_data import (
    LiveMarketFeed,
    LiveUnavailableError,
    normalize_candles,
    normalize_event,
    normalize_market,
    normalize_order_book,
    normalize_status,
    normalize_tags,
    normalize_trades,
    to_decimal,
)

UPSTREAM = "/api/v4/prediction"

UPSTREAM_MARKET = {
    "market_id": "631018",
    "event_id": "57678",
    "condition_id": "0xc8c5",
    "title": "Will the Republicans win the Mississippi Senate race in 2026?",
    "event_title": "Mississippi Senate Election Winner",
    "slug": "will-the-republicans-win-the-mississippi-senate-race-in-2026",
    "status": "active",
    "closed": False,
    "accepting_orders": True,
    "enable_order_book": False,
    "best_bid": "0.028",
    "best_ask": "0.030",
    "last_trade_price": "0.029",
    "volume": "2714976.2605729997",
    "liquidity": "24798.3354",
    "start_time": 1760389474,
    "end_time": 1793664000,
    "tags": None,
    "outcomes": [
        {"outcome": "Yes", "token_id": "tok-yes", "clob_token_id": "tok-yes", "price": "0.03"},
        {"outcome": "No", "token_id": "tok-no", "clob_token_id": "tok-no", "price": "0.09"},
    ],
}

UPSTREAM_BOOK = {
    "token_id": "tok-yes",
    "condition_id": "0xc8c5",
    # Upstream sends asks descending and bids ascending.
    "asks": [{"price": "0.999", "size": "10"}, {"price": "0.030", "size": "5"}],
    "bids": [{"price": "0.001", "size": "1"}, {"price": "0.028", "size": "2"}],
}


def make_client(handler) -> DexBuilderClient:
    config = DexBuilderConfig(
        DEXBUILDER_API_BASE="https://api.dexbuilder.test",
        DEXBUILDER_API_KEY="",
        DEXBUILDER_API_SECRET="",
    )
    return DexBuilderClient(config, transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def test_to_decimal_parses_strings_without_binary_float():
    assert to_decimal("0.1") + to_decimal("0.2") == to_decimal("0.3")
    assert to_decimal("") is None
    assert to_decimal(None) is None
    assert to_decimal("not-a-number") is None


def test_normalize_market_maps_upstream_shape():
    payload = normalize_market(UPSTREAM_MARKET)
    assert payload["id"] == "631018"
    assert payload["question"].startswith("Will the Republicans")
    assert payload["outcomes"] == ["Yes", "No"]
    assert payload["tokens"][0]["token_id"] == "tok-yes"
    assert payload["tokens"][0]["price"] == 0.03
    assert payload["prices"]["tok-no"] == 0.09
    assert payload["status"] == "ACTIVE"
    assert payload["best_bid"] == 0.028
    assert payload["best_ask"] == 0.03
    # mid = (bid + ask) / 2 computed in Decimal
    assert payload["mid_price"] == 0.029
    assert payload["source"] == "dexbuilder"
    assert payload["read_only"] is True


def test_normalize_market_handles_missing_quotes():
    payload = normalize_market({**UPSTREAM_MARKET, "best_bid": "", "best_ask": "", "last_trade_price": ""})
    assert payload["best_bid"] is None
    assert payload["best_ask"] is None
    assert payload["mid_price"] is None
    assert payload["last_trade_price"] is None


CLOSED_MARKET = {
    "market_id": "2316216",
    "event_id": "507693",
    "title": "Will Paris Saint-Germain FC win on 2026-05-30?",
    "status": "closed",
    "closed": True,
    "accepting_orders": False,
    "volume": "38427417.853250585",
    "liquidity": "0",
    "outcomes": [
        {"outcome": "Yes", "token_id": "tok-y", "clob_token_id": "tok-y", "price": "0"},
        {"outcome": "No", "token_id": "tok-n", "clob_token_id": "tok-n", "price": "1"},
    ],
}


def test_normalize_closed_market_derives_the_winner():
    payload = normalize_market(CLOSED_MARKET)
    assert payload["resolved"] is True
    assert payload["status"] == "CLOSED"
    assert payload["winning_outcome_index"] == 1
    assert payload["winning_outcome"] == "No"


def test_normalize_closed_market_without_a_single_winner():
    ambiguous = {
        **CLOSED_MARKET,
        "outcomes": [
            {"outcome": "Yes", "token_id": "tok-y", "price": "0.5"},
            {"outcome": "No", "token_id": "tok-n", "price": "0.5"},
        ],
    }
    payload = normalize_market(ambiguous)
    assert payload["resolved"] is True
    assert payload["winning_outcome_index"] is None
    assert payload["winning_outcome"] is None


def test_active_market_never_reports_a_winner():
    payload = normalize_market(
        {
            **CLOSED_MARKET,
            "status": "active",
            "closed": False,
            "outcomes": [
                {"outcome": "Yes", "token_id": "tok-y", "price": "1"},
                {"outcome": "No", "token_id": "tok-n", "price": "0"},
            ],
        }
    )
    assert payload["resolved"] is False
    assert payload["winning_outcome_index"] is None


def test_normalize_status_maps_aliases_to_upstream_values():
    assert normalize_status("active") == "active"
    assert normalize_status("resolved") == "closed"
    assert normalize_status("settled") == "closed"
    assert normalize_status(None) == "closed"


def test_normalize_order_book_sorts_best_price_first():
    payload = normalize_order_book(UPSTREAM_BOOK)
    assert [lvl[0] for lvl in payload["bids"]] == ["0.028", "0.001"]
    assert [lvl[0] for lvl in payload["asks"]] == ["0.03", "0.999"]
    assert payload["bids"][0][1] == 2.0
    assert payload["source"] == "dexbuilder"


def test_normalize_tags_and_events():
    tags = normalize_tags(
        {"items": [{"slug": "crypto", "label": {"en": "Crypto", "cn": "加密"}}, {"slug": "btc"}]}
    )
    assert tags == ["Crypto", "btc"]
    event = normalize_event(
        {
            "event_id": "ge_1",
            "slug": "ge-1",
            "title": {"en": "BNB Up or Down", "cn": "x"},
            "active": True,
            "closed": False,
            "start_date": 1793898021,
            "end_date": 1794074400,
            "volume": "12.5",
            "tags": [{"slug": "crypto", "label": {"en": "Crypto"}}],
        }
    )
    assert event["title"] == "BNB Up or Down"
    assert event["status"] == "ACTIVE"
    assert event["tags"] == ["Crypto"]
    assert event["total_volume"] == 12.5


def test_normalize_trades_and_candles():
    trades = normalize_trades(
        [
            {
                "id": "1",
                "market_id": "631018",
                "token_id": "tok-yes",
                "outcome": "Yes",
                "side": "buy",
                "price": "0.971000000000000000",
                "size": "51.730000000000000000",
                "created_at": 1793901519,
            }
        ]
    )
    assert trades[0]["side"] == "BUY"
    assert trades[0]["price"] == 0.971
    assert trades[0]["size"] == 51.73
    assert trades[0]["timestamp"].startswith("20")

    candles = normalize_candles(
        [{"t": 1793895930, "o": "0.031", "h": "0.032", "l": "0.030", "c": "0.031", "v": "0"}]
    )
    assert candles[0]["timestamp"] == 1793895930
    assert candles[0]["open"] == 0.031
    assert candles[0]["close"] == 0.031


# ---------------------------------------------------------------------------
# Feed behaviour
# ---------------------------------------------------------------------------


async def test_feed_caches_successful_reads():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"items": [UPSTREAM_MARKET], "total": 1})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    first = await feed.markets(limit=1)
    second = await feed.markets(limit=1)
    assert len(calls) == 1
    assert first["markets"][0]["id"] == "631018"
    assert second["markets"][0]["id"] == "631018"


async def test_feed_raises_when_upstream_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    with pytest.raises(LiveUnavailableError):
        await feed.markets(limit=1)


async def test_feed_maps_resolved_alias_to_closed_and_paginates():
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"items": [CLOSED_MARKET], "total": 1})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    payload = await feed.markets(status="resolved", limit=50, offset=100)
    query = dict(seen[0].params)
    assert query["status"] == "closed"
    assert query["offset"] == "100"
    assert query["limit"] == "50"
    assert payload["status"] == "closed"
    assert payload["offset"] == 100
    assert payload["markets"][0]["winning_outcome"] == "No"


async def test_feed_reports_more_pages_when_the_page_is_full():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [CLOSED_MARKET, CLOSED_MARKET], "total": 2},
        )

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    payload = await feed.markets(status="closed", limit=2, offset=0)
    assert payload["has_more"] is True
    assert payload["next_offset"] == 2


async def test_feed_serves_stale_value_when_upstream_breaks():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(200, json={"items": [UPSTREAM_MARKET], "total": 1})
        return httpx.Response(500, json={"detail": "boom"})

    feed = LiveMarketFeed(make_client(handler), ttl=0)
    first = await feed.markets(limit=1)
    # TTL expired -> refetch fails -> stale value is served instead of an error.
    second = await feed.markets(limit=1)
    assert first["markets"][0]["id"] == second["markets"][0]["id"] == "631018"


async def test_feed_opens_circuit_after_repeated_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    for _ in range(3):
        with pytest.raises(LiveUnavailableError):
            await feed.markets(limit=1)
    assert feed.status()["circuit_open"] is True
    assert feed.status()["consecutive_failures"] >= 3


async def test_price_history_falls_back_to_candlesticks():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/price_history"):
            return httpx.Response(404, json={"label": "NOT_FOUND", "message": "token not found"})
        return httpx.Response(
            200,
            json=[{"t": 1793895930, "o": "0.031", "h": "0.031", "l": "0.031", "c": "0.031", "v": "0"}],
        )

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    payload = await feed.price_history("tok-yes", interval="1h")
    assert payload["candles"][0]["close"] == 0.031


# ---------------------------------------------------------------------------
# HTTP surfaces
# ---------------------------------------------------------------------------


@pytest.fixture
def live_overrides():
    """Route the live endpoints at a mocked upstream (no network, no creds)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{UPSTREAM}/markets/631018/trades":
            return httpx.Response(200, json=[])
        if path == f"{UPSTREAM}/markets/631018":
            return httpx.Response(200, json=UPSTREAM_MARKET)
        if path == f"{UPSTREAM}/markets":
            return httpx.Response(200, json={"items": [UPSTREAM_MARKET], "total": 1})
        if path.endswith("/order_book"):
            return httpx.Response(200, json=UPSTREAM_BOOK)
        if path == f"{UPSTREAM}/tags":
            return httpx.Response(200, json={"items": [{"slug": "crypto", "label": {"en": "Crypto"}}]})
        if path == f"{UPSTREAM}/time":
            return httpx.Response(200, json={"server_time": 1793901786629})
        if path == f"{UPSTREAM}/events":
            return httpx.Response(200, json={"items": []})
        if path.endswith("/candlesticks"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "not mocked"})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    from app.main import app

    app.dependency_overrides[get_live_feed] = lambda: feed
    yield feed
    app.dependency_overrides.pop(get_live_feed, None)


async def test_live_markets_route(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/markets?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "dexbuilder"
    assert body["markets"][0]["id"] == "631018"
    assert body["markets"][0]["tokens"][0]["price"] == 0.03
    assert body["offset"] == 0
    assert body["has_more"] is False
    assert body["next_offset"] is None


async def test_live_markets_route_rejects_unknown_status(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/markets?status=bogus")
    assert r.status_code == 422
    assert "status must be one of" in r.json()["detail"]


async def test_live_markets_route_accepts_resolved_alias(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/markets?status=resolved&offset=100")
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert r.json()["offset"] == 100


async def test_live_market_detail_route(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/markets/631018")
    assert r.status_code == 200
    assert r.json()["mid_price"] == 0.029


async def test_live_order_book_route(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/tokens/tok-yes/order_book?depth=10")
    assert r.status_code == 200
    assert r.json()["bids"][0][0] == "0.028"


async def test_live_tags_and_time_routes(client, live_overrides):
    tags = await client.get("/api/v4/prediction/live/tags")
    assert tags.status_code == 200
    assert tags.json()["tags"] == ["Crypto"]
    clock = await client.get("/api/v4/prediction/live/time")
    assert clock.status_code == 200
    assert clock.json()["server_time"] == 1793901786629


async def test_live_status_route(client, live_overrides):
    r = await client.get("/api/v4/prediction/live/status")
    assert r.status_code == 200
    assert r.json()["public_reads"] is True
    assert r.json()["credentialed"] is False


async def test_live_route_returns_502_when_upstream_unavailable(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    feed = LiveMarketFeed(make_client(handler), ttl=60)
    from app.main import app

    app.dependency_overrides[get_live_feed] = lambda: feed
    try:
        r = await client.get("/api/v4/prediction/live/markets")
        assert r.status_code == 502
        assert r.json()["detail"] == "DEXBUILDER_UPSTREAM_UNAVAILABLE"
    finally:
        app.dependency_overrides.pop(get_live_feed, None)


async def test_public_upstream_reads_need_no_credentials():
    """The client signs only when a secret exists; public reads stay unsigned."""
    captured: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers)
        return httpx.Response(200, json={"items": [], "total": 0})

    client = make_client(handler)
    assert client.enabled is False
    assert client.public_reads is True
    await client.get_markets(limit=1)
    headers = captured[0]
    assert "timestamp" not in headers
    assert "authorization" not in headers


async def test_signed_request_includes_timestamp_header():
    captured: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers)
        return httpx.Response(200, json={"items": [], "total": 0})

    config = DexBuilderConfig(
        DEXBUILDER_API_BASE="https://api.dexbuilder.test",
        DEXBUILDER_API_KEY="key-123",
        DEXBUILDER_API_SECRET="secret-123",
    )
    client = DexBuilderClient(config, transport=httpx.MockTransport(handler))
    await client.get_markets(limit=1)
    headers = captured[0]
    assert headers["timestamp"]
    assert headers["sign"]
    assert headers["key"] == "key-123"


async def test_proxy_still_requires_api_key(client, monkeypatch):
    monkeypatch.setenv("DEXBUILDER_API_KEY", "")
    r = await client.get("/api/v4/dexbuilder/markets")
    assert r.status_code == 503
    assert r.json()["detail"] == "DEXBUILDER_NOT_CONFIGURED"
