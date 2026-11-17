"""DexBuilder API client: HMAC-SHA512 signed requests to api.dexbuilder.com.

The client is used by the proxy router and (optionally) by the frontend-facing
read endpoints when DexBuilder credentials are configured. When no API key is
set, the proxy returns HTTP 503 and the application falls back to its own data.

Signing follows the official DexBuilder authentication spec:

* request headers: ``KEY`` (API key), ``Timestamp`` (unix seconds) and
  ``SIGN`` (hexadecimal HMAC-SHA512 digest);
* signed message::

      METHOD + "\\n" + PATH + "\\n" + QUERY + "\\n"
      + HexEncode(SHA512(raw body)) + "\\n" + TIMESTAMP

* ``SIGN = HexEncode(HMAC_SHA512(api_secret, signed message))``

The query string inside the signed message must be byte-identical to the one
actually sent, so the client encodes it once and signs that exact string.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE = "https://api.dexbuilder.com"
DEFAULT_WS = "wss://broker.dexbuilder.com/ws/dex-builder/prediction"

#: SHA512 of an empty request body, as required by the signing spec.
EMPTY_BODY_SHA512 = hashlib.sha512(b"").hexdigest()


class DexBuilderAuthError(RuntimeError):
    """The upstream rejected the configured DexBuilder credentials.

    The upstream answers a bad credential with HTTP 401/403 and a
    machine-readable label (``INVALID_KEY``, ``INVALID_SIGNATURE``,
    ``IP_FORBIDDEN``, ``READ_ONLY``, ``FORBIDDEN``, ...). The label is kept so
    callers can report *why* the upstream refused the request.
    """

    def __init__(self, label: str, status_code: int, message: str = "") -> None:
        super().__init__(f"{label}: {message}" if message else label)
        self.label = label
        self.status_code = status_code
        self.message = message


def canonical_signature_message(
    method: str,
    path: str,
    query: str,
    body: str,
    timestamp: str,
) -> str:
    """Build the signed message exactly as the DexBuilder spec documents it."""
    body_hash = hashlib.sha512((body or "").encode("utf-8")).hexdigest()
    return f"{method.upper()}\n{path}\n{query or ''}\n{body_hash}\n{timestamp}"


def sign_payload(secret: str, message: str) -> str:
    """Hexadecimal HMAC-SHA512 digest of ``message`` keyed by ``secret``."""
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()


def _query_pairs(params: dict | list[tuple[str, Any]] | None) -> list[tuple[str, str]]:
    """Query pairs in the exact order they are sent (httpx-compatible)."""
    if not params:
        return []
    items = params.items() if isinstance(params, dict) else params
    pairs: list[tuple[str, str]] = []
    for key, value in items:
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        pairs.append((str(key), str(value)))
    return pairs


def _encode_query(params: dict | list[tuple[str, Any]] | None) -> str:
    """Canonical query string used inside the HMAC signed message."""
    pairs = _query_pairs(params)
    if not pairs:
        return ""
    return urlencode(pairs)


def _upstream_error(response: httpx.Response) -> tuple[str, str]:
    """Extract the upstream ``label``/``message`` pair from an error body."""
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - upstream may answer with plain text
        payload = {}
    if isinstance(payload, dict):
        label = str(payload.get("label") or f"HTTP_{response.status_code}")
        message = str(payload.get("message") or payload.get("detail") or "")
        return label, message
    return f"HTTP_{response.status_code}", ""


class DexBuilderConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        # Credentials are commonly kept in a local `.env` file.
        env_file=".env",
        env_file_encoding="utf-8",
    )

    DEXBUILDER_API_BASE: str = DEFAULT_BASE
    DEXBUILDER_API_KEY: str = ""
    DEXBUILDER_API_SECRET: str = ""
    DEXBUILDER_BROKER_ID: str = ""
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
        timestamp: str | None = None,
    ) -> dict[str, str]:
        """Build the HMAC-SHA512 signature headers. Empty when no secret.

        The upstream answers unauthenticated calls with
        ``MISSING_REQUIRED_HEADER: Missing required header: Timestamp`` and
        names the remaining headers ``KEY`` and ``SIGN``, so those exact names
        are sent (and no aliases, which would only confuse the gateway).
        """
        if not self.config.DEXBUILDER_API_SECRET:
            return {}
        stamp = timestamp if timestamp is not None else str(int(time.time()))
        message = canonical_signature_message(method, path, query, body, stamp)
        return {
            "KEY": self.config.DEXBUILDER_API_KEY,
            "Timestamp": stamp,
            "SIGN": sign_payload(self.config.DEXBUILDER_API_SECRET, message),
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | list[tuple[str, str]] | None = None,
        body: str = "",
        user_wallet: str | None = None,
    ) -> Any:
        """Perform an upstream request.

        Public reads are allowed without credentials (markets, books, candles,
        tags, trades); credentials only add the HMAC signature headers.

        Raises:
            DexBuilderAuthError: the upstream rejected the credentials
                (HTTP 401/403 with a machine-readable label).
        """
        if not self.public_reads:
            raise RuntimeError("DexBuilder API base is not configured")
        headers = {"Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"
        query = _encode_query(params)
        headers.update(self._sign(method, path, body, query))
        if user_wallet:
            headers["X-User-Wallet-Address"] = user_wallet
        # The signed query string must be byte-identical to the sent one, so
        # the URL is assembled here instead of letting httpx re-encode it.
        url = f"{path}?{query}" if query else path
        async with httpx.AsyncClient(
            base_url=self.config.DEXBUILDER_API_BASE,
            timeout=self.config.DEXBUILDER_TIMEOUT,
            transport=self.transport,
        ) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                content=body.encode("utf-8") if body else None,
            )
            if response.status_code in (401, 403):
                label, message = _upstream_error(response)
                raise DexBuilderAuthError(label, response.status_code, message)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    async def check_credentials(self) -> dict[str, Any]:
        """Probe the upstream with the configured credentials.

        The result never contains the API key or the API secret; it only says
        whether a credential is configured and how the upstream answered.
        """
        key_present = bool(self.config.DEXBUILDER_API_KEY.strip())
        secret_present = bool(self.config.DEXBUILDER_API_SECRET.strip())
        result: dict[str, Any] = {
            "configured": key_present,
            "key_present": key_present,
            "secret_present": secret_present,
            "scheme": "HMAC-SHA512",
            "headers": ["KEY", "Timestamp", "SIGN"],
            "authenticated": False,
            "upstream": None,
        }
        if not key_present or not secret_present:
            result["upstream"] = {
                "status": None,
                "label": "NOT_CONFIGURED",
                "message": "DEXBUILDER_API_KEY and DEXBUILDER_API_SECRET are required",
            }
            return result
        try:
            await self._request(
                "GET",
                "/api/v4/dexbuilder/assets",
            )
        except DexBuilderAuthError as exc:
            result["upstream"] = {
                "status": exc.status_code,
                "label": exc.label,
                "message": exc.message,
            }
            return result
        except Exception as exc:  # noqa: BLE001 - diagnostics never raise
            result["upstream"] = {
                "status": None,
                "label": "UPSTREAM_UNAVAILABLE",
                "message": str(exc)[:200],
            }
            return result
        result["authenticated"] = True
        result["upstream"] = {
            "status": 200,
            "label": "OK",
            "message": "the upstream accepted the configured credentials",
        }
        return result

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

    async def get_positions(self, user_wallet: str | None = None):
        return await self._request("GET", "/api/v4/broker/prediction/positions", user_wallet=user_wallet)

    async def get_settled_positions(self, user_wallet: str | None = None):
        return await self._request("GET", "/api/v4/broker/prediction/positions/settled", user_wallet=user_wallet)

    async def get_user_trades(self, user_wallet: str | None = None):
        return await self._request("GET", "/api/v4/broker/prediction/usertrades", user_wallet=user_wallet)

    async def get_orders(
        self,
        user_wallet: str | None = None,
        *,
        status: str | None = None,
        condition_id: str | None = None,
        event_id: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ):
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if condition_id:
            params["condition_id"] = condition_id
        if event_id:
            params["event_id"] = event_id
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET",
            "/api/v4/broker/prediction/orders",
            params=params or None,
            user_wallet=user_wallet,
        )

    async def get_order(self, order_id: str, user_wallet: str | None = None):
        return await self._request(
            "GET",
            f"/api/v4/broker/prediction/orders/{order_id}",
            user_wallet=user_wallet,
        )

    async def place_order(self, payload: dict[str, Any], user_wallet: str | None = None):
        body = json.dumps(payload, separators=(",", ":"))
        return await self._request(
            "POST",
            "/api/v4/broker/prediction/orders",
            body=body,
            user_wallet=user_wallet,
        )

    async def cancel_order(self, order_id: str, user_wallet: str | None = None):
        return await self._request(
            "DELETE",
            f"/api/v4/broker/prediction/orders/{order_id}",
            user_wallet=user_wallet,
        )

    async def cancel_orders_by_condition(self, condition_id: str, user_wallet: str | None = None):
        return await self._request(
            "DELETE",
            "/api/v4/broker/prediction/orders",
            params={"condition_id": condition_id},
            user_wallet=user_wallet,
        )

    async def get_account_book(
        self,
        user_wallet: str | None = None,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ):
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET",
            "/api/v4/broker/prediction/account_book",
            params=params or None,
            user_wallet=user_wallet,
        )

    async def get_claimable(self, user_wallet: str | None = None):
        return await self._request(
            "GET",
            "/api/v4/broker/prediction/claims/available",
            user_wallet=user_wallet,
        )

    async def claim_winnings(self, payload: dict[str, Any], user_wallet: str | None = None):
        body = json.dumps(payload, separators=(",", ":"))
        return await self._request(
            "POST",
            "/api/v4/broker/prediction/claims",
            body=body,
            user_wallet=user_wallet,
        )

    async def get_platform_assets(self):
        return await self._request("GET", "/api/v4/dexbuilder/assets")

    async def get_user_info(self, user_wallet: str | None = None):
        return await self._request("GET", "/api/v4/dexbuilder/user/info", user_wallet=user_wallet)

    async def get_deposit_history(
        self, user_wallet: str | None = None, *, page: int = 1, page_size: int = 20
    ):
        return await self._request(
            "GET",
            "/api/v4/dexbuilder/deposit/history",
            params={"page": page, "page_size": page_size},
            user_wallet=user_wallet,
        )

    async def get_withdraw_history(
        self, user_wallet: str | None = None, *, page: int = 1, page_size: int = 20
    ):
        return await self._request(
            "GET",
            "/api/v4/dexbuilder/withdraw/history",
            params={"page": page, "page_size": page_size},
            user_wallet=user_wallet,
        )

    async def create_deposit_sign_data(self, payload: dict[str, Any], user_wallet: str | None = None):
        body = json.dumps(payload, separators=(",", ":"))
        return await self._request(
            "POST",
            "/api/v4/dexbuilder/deposit/sign_data",
            body=body,
            user_wallet=user_wallet,
        )

    async def create_withdraw_sign_data(self, payload: dict[str, Any], user_wallet: str | None = None):
        body = json.dumps(payload, separators=(",", ":"))
        return await self._request(
            "POST",
            "/api/v4/dexbuilder/withdraw/sign_data",
            body=body,
            user_wallet=user_wallet,
        )

    async def submit_withdraw(self, payload: dict[str, Any], user_wallet: str | None = None):
        body = json.dumps(payload, separators=(",", ":"))
        return await self._request(
            "POST",
            "/api/v4/dexbuilder/withdraw/submit",
            body=body,
            user_wallet=user_wallet,
        )

    def decimal(self, value) -> Decimal:
        return Decimal(str(value))