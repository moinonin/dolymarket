"""Tests for deterministic multi-category oracle adapters and System One verifier."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.oracle import fetch_deterministic_spot, validate_oracle_feed
from app.services.oracle_evidence_s1 import (
    check_numeric_threshold,
    is_allowed_source_url,
    parse_kalshi_rules,
)
from app.services.oracle_verifier import (
    resolve_expired_no_data,
    verify_resolution_evidence,
)


def test_validate_oracle_feed_allows_new_deterministic_providers():
    assert validate_oracle_feed("fred:FEDFUNDS") == "fred:FEDFUNDS"
    assert validate_oracle_feed("nws:KNYC:F") == "nws:KNYC:F"
    assert validate_oracle_feed("stooq:^spx") == "stooq:^spx"


@pytest.mark.asyncio
async def test_fetch_deterministic_spot_fred_nws_stooq(monkeypatch):
    class _FakeResp:
        def __init__(self, status_code: int, text: str = "", json_data=None):
            self.status_code = status_code
            self.text = text
            self._json = json_data

        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url: str, headers=None):
            if "fred.stlouisfed.org" in url:
                return _FakeResp(200, "DATE,FEDFUNDS\n2026-09-01,4.25\n2026-10-01,.\n")
            if "api.weather.gov" in url:
                return _FakeResp(
                    200,
                    json_data={"properties": {"temperature": {"value": 20.0}, "timestamp": "2026-11-19T12:00:00Z"}},
                )
            if "stooq.com" in url:
                return _FakeResp(
                    200,
                    "Symbol,Date,Time,Open,High,Low,Close,Volume\n^SPX,2026-11-18,22:00:00,5900,5950,5890,5942.5,1000\n",
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("app.services.oracle.httpx.AsyncClient", _FakeClient)

    fred = await fetch_deterministic_spot("fred:FEDFUNDS")
    assert fred["observed_value"] == 4.25
    assert fred["observed_at"] == "2026-09-01"

    nws_f = await fetch_deterministic_spot("nws:KNYC:F")
    assert nws_f["observed_value"] == 68.0

    stooq = await fetch_deterministic_spot("stooq:^spx")
    assert stooq["observed_value"] == 5942.5


@pytest.mark.asyncio
async def test_system_one_verifier_supports_contradicts_and_blocks_ssrf(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    sup = await verify_resolution_evidence(
        "Will the bill pass before Friday?",
        "YES",
        evidence_text="Official press release: The bill was approved, signed, and enacted today.",
    )
    assert sup["verdict"] == "SUPPORTS"
    assert sup["confidence"] >= 0.65

    contra = await verify_resolution_evidence(
        "Will the bill pass before Friday?",
        "YES",
        evidence_text="Official update: The bill was rejected, failed in committee, and cancelled.",
    )
    assert contra["verdict"] == "CONTRADICTS"
    assert contra["confidence"] >= 0.65

    with pytest.raises(HTTPException) as exc:
        await verify_resolution_evidence(
            "Test?",
            "YES",
            source_url="http://127.0.0.1:8000/internal",
        )
    assert exc.value.status_code == 422


_KALSHI_GTA_RULES = (
    "Resolves Yes if Take-Two Interactive Software, Inc. (including Rockstar Games) "
    "publicly reports before January 1, 2027 that Grand Theft Auto VI has reached "
    "at least 36 million units sold-in.\n"
    "Outcome verified from MS Now, ABC, Fox News, Associated Press, BBC, "
    "The Wall Street Journal, Bloomberg News, CNBC, CBS, NBC, "
    "Take-Two Interactive Software, Inc. Investor Events, The Washington Post, "
    "CNN, The New York Times, and Reuters.\n"
    "If there is no data for the Underlying published by a Source Agency by the "
    "Expiration Date, all markets will resolve to No."
)


def test_kalshi_rule_parser_and_numeric_guard():
    rules = parse_kalshi_rules(_KALSHI_GTA_RULES)
    assert "36 million units sold-in" in (rules["resolves_yes_if"] or "")
    assert "reuters.com" in rules["allowed_domains"]
    assert "take2games.com" in rules["allowed_domains"]
    assert rules["no_data_resolves_no"] is True

    assert is_allowed_source_url("https://www.reuters.com/business/gta6", rules["allowed_domains"])
    assert is_allowed_source_url("https://ir.take2games.com/news", rules["allowed_domains"])
    assert not is_allowed_source_url("https://random-rumor-blog.example/gta6", rules["allowed_domains"])

    assert check_numeric_threshold("GTA VI sold-in 42 million units.", ">=", 36_000_000) is True
    assert check_numeric_threshold("GTA VI sold-in 28 million units.", ">=", 36_000_000) is False

    exp = resolve_expired_no_data(_KALSHI_GTA_RULES, has_verified_yes_evidence=False)
    assert exp == {"outcome": "NO", "confidence": 1.0, "mode": "kalshi_no_data_default"}
    assert resolve_expired_no_data(_KALSHI_GTA_RULES, has_verified_yes_evidence=True) is None


@pytest.mark.asyncio
async def test_kalshi_verifier_enforces_source_whitelist_and_numeric_guard(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    # Non-whitelisted source URL is rejected before model inference.
    with pytest.raises(HTTPException) as exc:
        await verify_resolution_evidence(
            "Will GTA VI sell 36 million units?",
            "YES",
            source_url="https://unverified-blog.example/gta6",
            evidence_text="Take-Two reported 42 million units sold-in.",
            resolution_criteria=_KALSHI_GTA_RULES,
            oracle_threshold=36_000_000,
            oracle_comparator=">=",
        )
    assert exc.value.status_code == 422

    # Whitelisted source + threshold met -> SUPPORTS.
    ok = await verify_resolution_evidence(
        "Will GTA VI sell 36 million units?",
        "YES",
        source_url="https://www.reuters.com/technology/gta6-sales",
        evidence_text=(
            "Take-Two Interactive Software announced in its Q4 earnings release that "
            "Grand Theft Auto VI has sold-in 42 million units worldwide."
        ),
        resolution_criteria=_KALSHI_GTA_RULES,
        oracle_threshold=36_000_000,
        oracle_comparator=">=",
    )
    assert ok["numeric_ok"] is True
    if ok["mode"].startswith("oracle_s1_onnx"):
        assert ok["verdict"] == "SUPPORTS"
        assert ok["confidence"] >= 0.85

    # Whitelisted source + below threshold (28M < 36M) -> blocked by numeric guard.
    below = await verify_resolution_evidence(
        "Will GTA VI sell 36 million units?",
        "YES",
        source_url="https://www.reuters.com/technology/gta6-sales-q1",
        evidence_text=(
            "Take-Two Interactive reported Grand Theft Auto VI reached 28 million units sold-in."
        ),
        resolution_criteria=_KALSHI_GTA_RULES,
        oracle_threshold=36_000_000,
        oracle_comparator=">=",
    )
    assert below["numeric_ok"] is False
    if below["mode"].startswith("oracle_s1_onnx"):
        assert below["verdict"] == "CONTRADICTS"
