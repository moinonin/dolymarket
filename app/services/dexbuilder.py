"""DexBuilder API client: HMAC-SHA256 signed requests to api.dexbuilder.com.

The client is used by the proxy router and (optionally) by the frontend-facing
read endpoints when DexBuilder credentials are configured. When no API key is
set, the proxy returns HTTP 503 and the application falls back to its own data.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE = "https://api.dexbuilder.com"
DEFAULT_WS = "wss://broker.dexbuilder.com/ws/dex-builder/prediction"


def _encode_query(params: dict | list[tuple[str, str]] | None) -> str:
    """Canonical query string used inside the HMAC signed message."""
    if not params:
        return ""
    items = params.items() if isinstance(params, dict) else params
    pairs = [(str(k), str(v)) for k, v in items if v is not None and str(v) != ""]
    return "&".join(f"{k}={v}" for k, v in pairs)


class DexBuilderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    DEXBUILDER_API_BASE: str = DEFAULT_BASE
    DEXBUILDER_API_KEY: str = ""
    DEXBUILDER_API_SECRET: str = ""
    DEXBUILDER_WS_URL: str = DEFAULT_WS
    DEXBUILDER_TIMEOUT: float = 10.0

    @property
    def enabled(self) -> bool:
        """Credentialed mode.

        The ``/api/v4/dexbuilder/*`` proxy namespace is credential-gated: the
        contract requires HTTP 503 ``DEXBUILDER_NOT_CONFIGURED`` when no API
        key is present.
        """
        return bool(self.DEXBUILDER_API_KEY.strip())

    @property
    def public_reads(self) -> bool:
        """Public upstream mode.

        DexBuilder serves markets, order books, candles, tags and trades
        without credentials, so those reads only need a reachable base URL.
        """
        return bool(self.DEXBUILDER_API_BASE.strip())


def get_config() -> DexBuilderConfig:
    return DexBuilderConfig()


class DexBuilderClient:
    def __init__(
        self,
        config: DexBuilderConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config or get_config()
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def public_reads(self) -> bool:
        return self.config.public_reads

    def _sign(
        self,
        method: str,
        path: str,
        body: str = "",
        query: str = "",
    ) -> dict[str, str]:
        """Build the HMAC-SHA256 signature headers. Empty when no secret.

        DexBuilder answers unauthenticated calls with
        ``MISSING_REQUIRED_HEADER: Missing required header: Timestamp``, so the
        canonical header name is ``Timestamp``. The broker's documented
        websocket auth uses ``t``/``key``/``sign``; the same names are sent
        here as a best effort, together with the ``X-DB-*`` aliases, until the
        official REST signing spec is published.
        """
        if not self.config.DEXBUILDER_API_SECRET:
            return {}
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{query}{body}"
        signature = hmac.new(
            self.config.DEXBUILDER_API_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Timestamp": timestamp,
            "key": self.config.DEXBUILDER_API_KEY,
            "sign": signature,
            "X-DB-KEY": self.config.DEXBUILDER_API_KEY,
            "X-DB-SIGN": signature,
            "X-DB-TIMESTAMP": timestamp,
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | list[tuple[str, str]] | None = None,
        body: str = "",
    ) -> Any:
        """Perform an upstream request.

        Public reads are allowed without credentials (markets, books, candles,
        tags, trades); credentials only add the HMAC signature headers.
        """
        if not self.public_reads:
            raise RuntimeError("DexBuilder API base is not configured")
        headers = {"Accept": "application/json"}
        query = _encode_query(params)
        headers.update(self._sign(method, path, body, query))
        async with httpx.AsyncClient(
            base_url=self.config.DEXBUILDER_API_BASE,
            timeout=self.config.DEXBUILDER_TIMEOUT,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_markets(
        self,
        status: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        params = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if limit:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return await self._request("GET", "/api/v4/prediction/markets", params=params or None)

    async def get_market(self, market_id: str):
        return await self._request("GET", f"/api/v4/prediction/markets/{market_id}")

    async def get_market_by_slug(self, slug: str):
        return await self._request("GET", f"/api/v4/prediction/markets/slug/{slug}")

    async def get_events(self, status: str | None = None, category: str | None = None, limit: int = 50):
        params = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if limit:
            params["limit"] = limit
        return await self._request("GET", "/api/v4/prediction/events", params=params or None)

    async def get_event(self, event_id: str):
        return await self._request("GET", f"/api/v4/prediction/events/{event_id}")

    async def get_event_by_slug(self, slug: str):
        return await self._request("GET", f"/api/v4/prediction/events/slug/{slug}")

    async def get_tags(self):
        return await self._request("GET", "/api/v4/prediction/tags")

    async def get_order_book(self, token_id: str):
        return await self._request("GET", f"/api/v4/prediction/tokens/{token_id}/order_book")

    async def get_price(self, token_id: str):
        return await self._request("GET", f"/api/v4/prediction/tokens/{token_id}/price")

    async def get_prices(self, ids: list[str]):
        # DexBuilder expects repeated `token_ids` query params.
        params = [("token_ids", i) for i in ids]
        return await self._request("GET", "/api/v4/prediction/tokens/prices", params=params)

    async def get_ticker(self, token_id: str):
        return await self._request("GET", f"/api/v4/prediction/tokens/{token_id}/ticker")

    async def get_price_history(
        self,
        token_id: str,
        interval: str = "1h",
        from_ms: int | None = None,
        to_ms: int | None = None,
    ):
        """Price history. Upstream requires `interval` plus a millisecond range."""
        params: dict[str, str] = {"interval": interval}
        if from_ms is not None:
            params["from"] = str(int(from_ms))
        if to_ms is not None:
            params["to"] = str(int(to_ms))
        return await self._request(
            "GET",
            f"/api/v4/prediction/tokens/{token_id}/price_history",
            params=params,
        )

    async def get_candlesticks(
        self,
        token_id: str,
        interval: str = "1m",
        from_ms: int | None = None,
        to_ms: int | None = None,
        limit: int | None = None,
    ):
        """OHLCV candles for a token."""
        params: dict[str, str] = {"interval": interval}
        if from_ms is not None:
            params["from"] = str(int(from_ms))
        if to_ms is not None:
            params["to"] = str(int(to_ms))
        if limit is not None:
            params["limit"] = str(int(limit))
        return await self._request(
            "GET",
            f"/api/v4/prediction/tokens/{token_id}/candlesticks",
            params=params,
        )

    async def get_market_trades(self, market_id: str, limit: int = 50):
        params = {"limit": limit} if limit else None
        return await self._request(
            "GET",
            f"/api/v4/prediction/markets/{market_id}/trades",
            params=params,
        )

    async def get_time(self):
        return await self._request("GET", "/api/v4/prediction/time")

    async def get_positions(self):
        return await self._request("GET", "/api/v4/prediction/positions")

    async def get_settled_positions(self):
        return await self._request("GET", "/api/v4/prediction/positions/settled")

    async def get_user_trades(self):
        return await self._request("GET", "/api/v4/prediction/usertrades")

    async def get_orders(self):
        return await self._request("GET", "/api/v4/prediction/orders")

    def decimal(self, value) -> Decimal:
        return Decimal(str(value))