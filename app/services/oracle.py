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
    outcomes: list[str] | None = None,
) -> dict[str, Any]:
    """Score resolution criteria clarity 0..100 across source, predicate, time, and edge cases."""
    from app.services.oracle_s1 import get_oracle_decision_model

    text = (resolution_criteria or "").strip()
    lower = text.lower()
    s1 = get_oracle_decision_model().predict(
        text, question=question, end_date=end_date, oracle_feed=oracle_feed
    )
    flags: list[str] = []
    score = 0

    has_any_exchange = bool(re.search(r"\bany\s+(exchange|source|platform|market)\b", f"{question or ''} {lower}", re.I))
    has_source_rx = bool(oracle_feed or any(tok in lower for tok in _AUTHORITATIVE_SOURCES))
    has_source_s1 = bool(s1 and s1.get("has_authoritative_source", 0.0) >= 0.55)
    if (has_source_rx or has_source_s1) and not has_any_exchange:
        score += 25
    else:
        flags.append(
            "Vague source ('any exchange/source') — name a specific exchange or feed"
            if has_any_exchange
            else "No authoritative source or URL cited"
        )

    is_binary = not outcomes or [o.strip().upper() for o in outcomes] == ["YES", "NO"]
    is_open_ended = bool(question and re.match(r"^\s*(who|which|what)\b", question, re.I))
    has_pred_rx = bool(any(tok in lower for tok in _PREDICATE_TERMS) or re.search(r"\b\d+(\.\d+)?%?\b", lower))
    has_pred_s1 = bool(s1 and s1.get("has_unambiguous_predicate", 0.0) >= 0.50)
    if (has_pred_rx or has_pred_s1) and not (is_binary and is_open_ended):
        score += 25
    else:
        flags.append(
            "Open-ended question ('Who/Which/What') requires binary 'Will ...?' framing or multi-outcome options"
            if (is_binary and is_open_ended)
            else "Missing unambiguous numeric or binary predicate"
        )

    has_relative_next = bool(re.search(r"\bnext\b", f"{question or ''} {lower}", re.I))
    has_abs_year = bool(re.search(r"\b20\d{2}\b", f"{question or ''} {lower}"))
    has_time_rx = bool(end_date is not None or any(tok in lower for tok in _TIME_TERMS))
    has_time_s1 = bool(s1 and s1.get("has_explicit_deadline", 0.0) >= 0.55)
    if (has_time_rx or has_time_s1) and not (has_relative_next and end_date is None and not has_abs_year):
        score += 25
    else:
        flags.append(
            "Relative timeframe ('next') without an explicit year or end_date"
            if (has_relative_next and end_date is None and not has_abs_year)
            else "Missing explicit resolution timestamp or UTC window"
        )

    has_weasel = any(w in lower for w in _WEASEL_TERMS)
    has_s1_subjective = bool(s1 and s1.get("has_subjective_ambiguity", 0.0) >= 0.80)
    if len(text) >= 35 and not has_weasel and not has_s1_subjective:
        score += 25
    else:
        flags.append("Criteria too brief or contains subjective wording")

    grade = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    out: dict[str, Any] = {
        "score": score,
        "grade": grade,
        "flags": flags,
        "engine": "dolymarket_s1" if s1 else "regex",
    }
    if s1:
        out["category"] = s1["category"]
    return out


LIVE_ORACLE_PROVIDERS = frozenset({"gate", "coingecko", "fred", "nws", "stooq"})


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

    if prov == "fred":
        series_id = symbol.upper()
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"FRED oracle HTTP {resp.status_code}")
            lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
            for ln in reversed(lines[1:]):
                parts = ln.split(",", 1)
                if len(parts) == 2 and parts[1] not in ("", "."):
                    try:
                        val = float(Decimal(parts[1]))
                        return {
                            "feed": raw,
                            "observed_value": val,
                            "source_url": url,
                            "observed_at": parts[0],
                        }
                    except Exception:
                        continue
            raise HTTPException(status_code=502, detail=f"FRED series {series_id} has no valid observation")

    if prov == "nws":
        parts = symbol.split(":", 1)
        station = parts[0].upper()
        unit = parts[1].upper() if len(parts) > 1 else "C"
        url = f"https://api.weather.gov/stations/{station}/observations/latest"
        headers = {"User-Agent": "dolymarket-oracle/1.0", "Accept": "application/geo+json"}
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"NWS oracle HTTP {resp.status_code}")
            props = (resp.json() or {}).get("properties") or {}
            temp_c = (props.get("temperature") or {}).get("value")
            if temp_c is None:
                raise HTTPException(status_code=502, detail=f"NWS station {station} missing temperature")
            val = Decimal(str(temp_c))
            if unit == "F":
                val = val * Decimal("1.8") + Decimal("32")
            return {
                "feed": raw,
                "observed_value": float(val.quantize(Decimal("0.01"))),
                "source_url": url,
                "observed_at": props.get("timestamp") or now_iso,
            }

    if prov == "stooq":
        sym = symbol.lower()
        url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Stooq oracle HTTP {resp.status_code}")
            lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
            if len(lines) >= 2:
                cols = lines[1].split(",")
                # Header: Symbol,Date,Time,Open,High,Low,Close,Volume
                if len(cols) >= 7 and cols[6] not in ("", "N/D"):
                    return {
                        "feed": raw,
                        "observed_value": float(Decimal(cols[6])),
                        "source_url": url,
                        "observed_at": f"{cols[1]}T{cols[2]}" if len(cols) > 2 else now_iso,
                    }
            raise HTTPException(status_code=502, detail=f"Stooq missing close price for {sym}")

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
