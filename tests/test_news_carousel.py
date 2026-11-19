"""Tests for multi-source news carousel service & GET /api/v4/prediction/news/carousel."""
from __future__ import annotations

import pytest

from app.services.news_carousel import build_news_carousel, parse_rss_xml
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


def test_parse_rss_xml_extracts_title_caption_and_https_image():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel>
        <item>
          <title>Bitcoin surges past $100,000 on ETF inflows</title>
          <description>&lt;p&gt;Spot Bitcoin ETFs saw record institutional demand.&lt;/p&gt;</description>
          <link>https://www.coindesk.com/markets/btc-100k</link>
          <pubDate>Thu, 19 Nov 2026 12:00:00 GMT</pubDate>
          <media:thumbnail url="https://cdn.coindesk.com/images/btc-hero.jpg" />
        </item>
        <item>
          <title>Unsafe image filtered out</title>
          <description>Plain HTTP image should be dropped.</description>
          <link>https://example.com/item</link>
          <media:thumbnail url="http://insecure.example/img.jpg" />
        </item>
      </channel>
    </rss>"""
    items = parse_rss_xml(xml, "CoinDesk", "Crypto")
    assert len(items) == 2
    assert items[0]["news_title"] == "Bitcoin surges past $100,000 on ETF inflows"
    assert items[0]["caption"] == "Spot Bitcoin ETFs saw record institutional demand."
    assert items[0]["image_url"] == "https://cdn.coindesk.com/images/btc-hero.jpg"
    assert items[0]["source"] == "CoinDesk"
    assert items[1]["image_url"] is None


async def test_build_news_carousel_matches_items_to_best_active_market():
    active_events = [
        {
            "event_id": "ev-btc",
            "market_id": "mkt-btc",
            "slug": "btc-150k",
            "title": "Bitcoin $150k in 2026",
            "question": "Will Bitcoin close above $150,000?",
            "category": "Crypto",
            "volume": 5000.0,
            "yes_pct": 62,
        },
        {
            "event_id": "ev-fed",
            "market_id": "mkt-fed",
            "slug": "fed-rate-cut",
            "title": "Fed Rate Cut December",
            "question": "Will the Federal Reserve cut interest rates in December?",
            "category": "Economics",
            "volume": 8000.0,
            "yes_pct": 71,
        },
    ]
    raw_items = [
        {
            "news_title": "Bitcoin hits new cycle high as institutional ETF demand accelerates",
            "caption": "BTC rallied 6% overnight.",
            "source": "CoinDesk",
            "article_url": "https://www.coindesk.com/btc",
            "image_url": "https://cdn.coindesk.com/btc.jpg",
            "published_at": "2026-11-19T12:00:00Z",
            "hint_category": "Crypto",
            "provider": "rss",
        },
        {
            "news_title": "Federal Reserve signals December interest rate cut after CPI cools",
            "caption": "FOMC officials pointed to softer inflation data.",
            "source": "Reuters",
            "article_url": "https://www.reuters.com/fed",
            "image_url": "https://cdn.reuters.com/fed.jpg",
            "published_at": "2026-11-19T13:00:00Z",
            "hint_category": "Economics",
            "provider": "gdelt",
        },
    ]
    slides = await build_news_carousel(active_events, limit=6, raw_items=raw_items)
    assert len(slides) == 2
    by_src = {s["source"]: s for s in slides}
    assert by_src["CoinDesk"]["market_slug"] == "btc-150k"
    assert by_src["CoinDesk"]["yes_pct"] == 62
    assert by_src["Reuters"]["market_slug"] == "fed-rate-cut"
    assert by_src["Reuters"]["yes_pct"] == 71


async def test_news_carousel_endpoint_returns_linked_slides(client, monkeypatch):
    h = await auth_headers(client, "news_user@example.com")
    await client.post("/api/v1/collateral/deposit", json={"amount": 200}, headers=h)
    r_m = await client.post(
        "/api/v4/prediction/community/markets",
        json={
            "title": "Bitcoin $150k Q4",
            "question": "Will Bitcoin reach $150k?",
            "category": "Crypto",
            "resolution_criteria": "Resolves Yes if CoinGecko BTC >= $150000.",
            "end_date": "2027-06-01T00:00:00Z",
            "initial_liquidity_usdc": 50,
        },
        headers=h,
    )
    assert r_m.status_code == 201, r_m.text
    slug = r_m.json()["slug"]

    async def _fake_fetch(*, force_refresh: bool = False):
        return [
            {
                "news_title": "Bitcoin ETF inflows hit weekly record",
                "caption": "Crypto funds added $1.4B in fresh capital.",
                "source": "CNBC",
                "article_url": "https://www.cnbc.com/btc",
                "image_url": "https://image.cnbcfm.com/btc.jpg",
                "published_at": "2026-11-19T14:00:00Z",
                "hint_category": "Crypto",
                "provider": "rss",
            }
        ]

    monkeypatch.setattr("app.services.news_carousel.fetch_raw_news", _fake_fetch)
    resp = await client.get("/api/v4/prediction/news/carousel?limit=8")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sources"] == ["rss", "gdelt", "currents", "wikimedia"]
    assert len(data["items"]) == 1
    assert data["items"][0]["market_slug"] == slug
    assert data["items"][0]["source"] == "CNBC"
    assert data["items"][0]["image_url"] == "https://image.cnbcfm.com/btc.jpg"
