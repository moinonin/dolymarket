"""Oracle Clarity Score and deterministic price/event resolution feeds."""
from __future__ import annotations

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


async def fetch_deterministic_spot(feed: str) -> dict[str, Any]:
    """Fetch a verifiable spot observation for a deterministic feed string."""
    raw = feed.strip()
    if ":" not in raw:
        raise HTTPException(status_code=422, detail="Feed must be formatted as '<provider>:<symbol>'")
    provider, symbol = raw.split(":", 1)
    prov = provider.lower()
    now_iso = datetime.now(UTC).isoformat()

    if prov == "static":
        try:
            val = Decimal(symbol)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid static feed numeric value") from exc
        return {
            "feed": raw,
            "observed_value": float(val),
            "source_url": "internal://static-oracle-test",
            "observed_at": now_iso,
        }

    if prov == "gate":
        pair = symbol.upper().replace("/", "_")
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
) -> dict[str, Any]:
    """Evaluate ``observed_value <comparator> threshold`` -> outcome index 0 (YES) or 1 (NO)."""
    spot = await fetch_deterministic_spot(feed)
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
