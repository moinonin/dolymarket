"""Oracle Clarity Score and deterministic price/event resolution feeds."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException

_AUTHORITATIVE_SOURCES = (
    "http://",
    "https://",
    "pyth",
    "chainlink",
    "coingecko",
    "gate",
    "binance",
    "coinbase",
    "sec",
    "bls",
    "fed",
    "federal reserve",
    "reuters",
    "associated press",
    "espn",
    "noaa",
    "official",
)
_PREDICATE_TERMS = (
    "resolves yes",
    "resolves no",
    ">=",
    "<=",
    ">",
    "<",
    "above",
    "below",
    "at or above",
    "at or below",
    "strictly",
    "equal to",
    "binary",
    "closes above",
    "closes below",
)
_TIME_TERMS = ("utc", "est", "pst", "gmt", "202", "deadline", "before ", "by ", "at close", "expir")
_WEASEL_TERMS = ("maybe", "probably", "vibes", "subjective", "at my discretion", "tbd")


def compute_clarity_score(
    resolution_criteria: str | None,
    *,
    question: str | None = None,
    end_date: Any = None,
    oracle_feed: str | None = None,
) -> dict[str, Any]:
    """Score resolution criteria clarity 0..100 across source, predicate, time, and edge cases."""
    text = (resolution_criteria or "").strip()
    lower = text.lower()
    flags: list[str] = []
    score = 0

    if oracle_feed or any(tok in lower for tok in _AUTHORITATIVE_SOURCES):
        score += 25
    else:
        flags.append("No authoritative source or URL cited")

    if any(tok in lower for tok in _PREDICATE_TERMS) or re.search(r"\b\d+(\.\d+)?%?\b", lower):
        score += 25
    else:
        flags.append("Missing unambiguous numeric or binary predicate")

    if end_date is not None or any(tok in lower for tok in _TIME_TERMS):
        score += 25
    else:
        flags.append("Missing explicit resolution timestamp or UTC window")

    has_weasel = any(w in lower for w in _WEASEL_TERMS)
    if len(text) >= 35 and not has_weasel:
        score += 25
    else:
        flags.append("Criteria too brief or contains subjective wording")

    grade = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    return {"score": score, "grade": grade, "flags": flags}


LIVE_ORACLE_PROVIDERS = frozenset({"gate", "coingecko"})


def validate_oracle_feed(feed: str, *, allow_static: bool = False) -> str:
    """Validate `<provider>:<symbol>` format and enforce provider allowlist."""
    raw = (feed or "").strip()
    if ":" not in raw:
        raise HTTPException(
            status_code=422, detail="Feed must be formatted as '<provider>:<symbol>'"
        )
    provider, symbol = raw.split(":", 1)
    prov = provider.strip().lower()
    sym = symbol.strip()
    if not sym:
        raise HTTPException(status_code=422, detail="Oracle feed symbol cannot be empty")
    if prov == "static":
        is_prod = os.environ.get("APP_ENV", "").strip().lower() == "production"
        if not allow_static or (
            is_prod and os.environ.get("ALLOW_STATIC_ORACLE", "").strip() != "1"
        ):
            raise HTTPException(
                status_code=422,
                detail="static oracle provider is not allowed for community or production markets",
            )
        try:
            Decimal(sym)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid static feed numeric value") from exc
        return f"static:{sym}"
    if prov not in LIVE_ORACLE_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported oracle provider '{provider}'; allowed: {', '.join(sorted(LIVE_ORACLE_PROVIDERS))}",
        )
    return f"{prov}:{sym}"


async def fetch_deterministic_spot(
    feed: str,
    *,
    at_dt: datetime | None = None,
) -> dict[str, Any]:
    """Fetch a verifiable spot (or historical 1m close at ``at_dt``) for a feed string."""
    raw = feed.strip()
    if ":" not in raw:
        raise HTTPException(status_code=422, detail="Feed must be formatted as '<provider>:<symbol>'")
    provider, symbol = raw.split(":", 1)
    prov = provider.lower()
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    if prov == "static":
        is_prod = os.environ.get("APP_ENV", "").strip().lower() == "production"
        if is_prod and os.environ.get("ALLOW_STATIC_ORACLE", "").strip() != "1":
            raise HTTPException(
                status_code=422, detail="static oracle provider is disabled in production"
            )
        try:
            val = Decimal(symbol)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid static feed numeric value") from exc
        return {
            "feed": raw,
            "observed_value": float(val),
            "source_url": "internal://static-oracle-test",
            "observed_at": (at_dt.astimezone(UTC).isoformat() if at_dt else now_iso),
        }

    if prov == "gate":
        pair = symbol.upper().replace("/", "_")
        if at_dt is not None:
            at_utc = at_dt.replace(tzinfo=UTC) if at_dt.tzinfo is None else at_dt.astimezone(UTC)
            if (now - at_utc).total_seconds() > 60:
                ts = int(at_utc.timestamp())
                c_url = (
                    f"https://api.gateio.ws/api/v4/spot/candlesticks"
                    f"?currency_pair={pair}&interval=1m&to={ts}&limit=1"
                )
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(c_url)
                    if resp.status_code == 200:
                        candles = resp.json()
                        if isinstance(candles, list) and candles and len(candles[0]) >= 3:
                            # Gate candle format: [ts, quote_vol, close, high, low, open, ...]
                            close_px = float(Decimal(str(candles[0][2])))
                            return {
                                "feed": raw,
                                "observed_value": close_px,
                                "source_url": c_url,
                                "observed_at": at_utc.isoformat(),
                            }
                if (now - at_utc).total_seconds() > 3600:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Gate historical candle unavailable for {pair} at {at_utc.isoformat()}",
                    )
        url = f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={pair}"
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Gate oracle HTTP {resp.status_code}")
            data = resp.json()
            if not isinstance(data, list) or not data or "last" not in data[0]:
                raise HTTPException(status_code=502, detail=f"Gate oracle missing pair {pair}")
            return {
                "feed": raw,
                "observed_value": float(Decimal(str(data[0]["last"]))),
                "source_url": url,
                "observed_at": now_iso,
            }

    if prov == "coingecko":
        coin = symbol.lower()
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"CoinGecko oracle HTTP {resp.status_code}")
            data = resp.json()
            price = (data.get(coin) or {}).get("usd")
            if price is None:
                raise HTTPException(status_code=502, detail=f"CoinGecko missing coin {coin}")
            return {
                "feed": raw,
                "observed_value": float(Decimal(str(price))),
                "source_url": url,
                "observed_at": now_iso,
            }

    raise HTTPException(status_code=422, detail=f"Unsupported deterministic oracle provider: {provider}")


async def evaluate_deterministic_feed(
    feed: str,
    threshold: Decimal,
    comparator: str = ">=",
    *,
    at_dt: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate ``observed_value <comparator> threshold`` -> outcome index 0 (YES) or 1 (NO)."""
    spot = await fetch_deterministic_spot(feed, at_dt=at_dt)
    obs = Decimal(str(spot["observed_value"]))
    thr = Decimal(str(threshold))

    if comparator == ">=":
        yes_wins = obs >= thr
    elif comparator == ">":
        yes_wins = obs > thr
    elif comparator == "<=":
        yes_wins = obs <= thr
    elif comparator == "<":
        yes_wins = obs < thr
    else:
        raise HTTPException(status_code=422, detail="comparator must be one of >=, >, <=, <")

    return {
        **spot,
        "threshold": float(thr),
        "comparator": comparator,
        "winning_outcome_index": 0 if yes_wins else 1,
    }
