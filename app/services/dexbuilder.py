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


class DexBuilderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    DEXBUILDER_API_BASE: str = DEFAULT_BASE
    DEXBUILDER_API_KEY: str = ""
    DEXBUILDER_API_SECRET: str = ""
    DEXBUILDER_WS_URL: str = DEFAULT_WS

    @property
    def enabled(self) -> bool:
        return bool(self.DEXBUILDER_API_KEY.strip())


def get_config() -> DexBuilderConfig:
    return DexBuilderConfig()


class DexBuilderClient:
    def __init__(self, config: DexBuilderConfig | None = None):
        self.config = config or get_config()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _sign(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Build the HMAC-SHA256 signature headers. Empty when no secret."""
        if not self.config.DEXBUILDER_API_SECRET:
            return {}
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        signature = hmac.new(
            self.config.DEXBUILDER_API_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-DB-KEY": self.config.DEXBUILDER_API_KEY,
            "X-DB-SIGN": signature,
            "X-DB-TIMESTAMP": timestamp,
        }

    async def _request(self, method: str, path: str, params: dict | None = None) -> Any:
        if not self.enabled:
            raise RuntimeError("DexBuilder is not configured")
        headers = {"Accept": "application/json"}
        headers.update(self._sign(method, path))
        if self.config.DEXBUILDER_API_KEY:
            headers.setdefault("Authorization", f"Bearer {self.config.DEXBUILDER_API_KEY}")
        async with httpx.AsyncClient(base_url=self.config.DEXBUILDER_API_BASE, timeout=15.0) as client:
            response = await client.request(method, path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_markets(self, status: str | None = None, category: str | None = None, limit: int = 50):
        params = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if limit:
            params["limit"] = limit
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

    async def get_price_history(self, token_id: str):
        return await self._request("GET", f"/api/v4/prediction/tokens/{token_id}/price_history")

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