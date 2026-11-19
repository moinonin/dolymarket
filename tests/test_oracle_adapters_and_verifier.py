"""Tests for deterministic multi-category oracle adapters and System One verifier."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.oracle import fetch_deterministic_spot, validate_oracle_feed
from app.services.oracle_verifier import verify_resolution_evidence


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
    assert sup["confidence"] >= 0.85

    contra = await verify_resolution_evidence(
        "Will the bill pass before Friday?",
        "YES",
        evidence_text="Official update: The bill was rejected, failed in committee, and cancelled.",
    )
    assert contra["verdict"] == "CONTRADICTS"
    assert contra["confidence"] >= 0.85

    with pytest.raises(HTTPException) as exc:
        await verify_resolution_evidence(
            "Test?",
            "YES",
            source_url="http://127.0.0.1:8000/internal",
        )
    assert exc.value.status_code == 422
