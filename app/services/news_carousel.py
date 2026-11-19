"""Multi-source cached news carousel service linking live headlines & photos to active markets.

Combines four free/low-friction news + media providers with a 15-minute TTL cache:
1. Direct News RSS feeds (BBC, CNBC, CoinDesk, NYT) — zero key, high-res media thumbnails + captions
2. GDELT DOC 2.0 API (filtered to trusted Source Agencies) — zero key, global news + socialimage
3. Currents API (optional, enabled when CURRENTS_API_KEY is set) — structured JSON + images
4. Wikimedia REST API — high-res topic photo fallback when an article lacks a valid HTTPS image
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("app.news_carousel")

CACHE_TTL_SECONDS = 900.0  # 15 minutes
_MAX_FEED_BYTES = 262_144  # 256 KB hard cap per feed
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "will", "have", "has",
        "are", "was", "were", "been", "into", "over", "after", "before", "about",
        "more", "than", "their", "what", "when", "where", "which", "while", "who",
        "why", "how", "says", "said", "new", "year", "years", "market", "markets",
        "price", "prices", "today", "week", "month", "day", "could", "would",
    }
)

_RSS_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("BBC Business", "Economics", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("BBC World", "Politics", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NYT Politics", "Politics", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"),
    ("CNBC", "Financials", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "Financials", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CoinDesk", "Crypto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "Crypto", "https://cointelegraph.com/rss"),
    ("NYT Business", "Companies", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("BBC Sport", "Sports", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("ESPN", "Sports", "https://www.espn.com/espn/rss/news"),
    ("BBC Tech", "Tech & Science", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("BBC Science", "Climate", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("BBC Culture", "Culture", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
)

_GDELT_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=(domain:reuters.com%20OR%20domain:apnews.com%20OR%20domain:bbc.com"
    "%20OR%20domain:cnbc.com%20OR%20domain:bloomberg.com)%20sourcelang:eng"
    "&mode=artlist&maxrecords=18&sort=datedesc&format=json"
)

_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "crypto": frozenset({"bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "stablecoin", "defi", "coinbase", "binance", "blockchain", "token"}),
    "economics": frozenset({"fed", "fomc", "inflation", "cpi", "gdp", "rates", "treasury", "recession", "jobs", "payroll", "tariff", "economy", "bank"}),
    "financials": frozenset({"stock", "stocks", "nasdaq", "sp500", "dow", "earnings", "ipo", "wall", "shares", "etf", "bond", "yield"}),
    "politics": frozenset({"senate", "congress", "president", "election", "trump", "biden", "white", "house", "bill", "vote", "supreme", "court", "policy", "war", "nato"}),
    "tech": frozenset({"openai", "anthropic", "google", "apple", "nvidia", "meta", "microsoft", "tesla", "spacex", "gpt", "model", "chip", "semiconductor"}),
    "sports": frozenset({"premier", "league", "nba", "nfl", "mlb", "fifa", "champions", "olympics", "match", "finals", "cup", "liverpool", "arsenal"}),
    "culture": frozenset({"gta", "rockstar", "movie", "oscar", "grammy", "box", "office", "game", "gaming", "netflix", "album", "film"}),
}

_WIKI_TOPIC_MAP: tuple[tuple[str, str], ...] = (
    ("bitcoin", "Bitcoin"),
    ("btc", "Bitcoin"),
    ("ethereum", "Ethereum"),
    ("eth", "Ethereum"),
    ("solana", "Solana_(blockchain_platform)"),
    ("fed", "Federal_Reserve"),
    ("inflation", "Inflation"),
    ("cpi", "Consumer_price_index"),
    ("gta", "Grand_Theft_Auto_VI"),
    ("spacex", "SpaceX_Starship"),
    ("openai", "OpenAI"),
    ("apple", "Apple_Inc."),
    ("nvidia", "Nvidia"),
    ("senate", "United_States_Senate"),
    ("election", "United_States_Capitol"),
    ("climate", "Climate_change"),
    ("weather", "Weather"),
)

# Simple in-memory cache: (expires_monotonic, raw_items)
_raw_news_cache: tuple[float, list[dict[str, Any]]] | None = None
_wiki_image_cache: dict[str, str | None] = {}


def _clean_text(raw: str | None, max_len: int = 200) -> str:
    if not raw:
        return ""
    unescaped = html.unescape(raw)
    stripped = _TAG_RE.sub(" ", unescaped)
    collapsed = _WS_RE.sub(" ", stripped).strip()
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


def _valid_https_image(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if not u.startswith("https://") or len(u) > 1000:
        return None
    low = u.lower()
    if any(bad in low for bad in ("favicon", "logo_small", "1x1", "pixel.", "sprite", ".svg")):
        return None
    return u


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS}


def _upgrade_image_res(url: str) -> str:
    """Request HD variants from known newsroom CDNs (e.g. BBC 240px -> 976px)."""
    return re.sub(
        r"(https://ichef\.bbci\.co\.uk/(?:ace/standard|news)/)\d+/",
        r"\g<1>976/",
        url,
    )


def _extract_rss_image(item: ET.Element) -> str | None:
    best_url: str | None = None
    best_width = -1
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("content") or tag.endswith("thumbnail") or tag.endswith("enclosure"):
            url = elem.attrib.get("url")
            mtype = (elem.attrib.get("type") or "").lower()
            if url and (not mtype or mtype.startswith("image/") or tag.endswith("thumbnail")):
                valid = _valid_https_image(url)
                if valid:
                    try:
                        w = int(elem.attrib.get("width") or 0)
                    except ValueError:
                        w = 0
                    # Prefer media:content over thumbnail when width is unspecified
                    score = w if w > 0 else (500 if tag.endswith("content") else 240)
                    if score > best_width:
                        best_width = score
                        best_url = _upgrade_image_res(valid)
    return best_url


def parse_rss_xml(xml_bytes: bytes, source_name: str, default_category: str) -> list[dict[str, Any]]:
    """Parse an RSS/Atom XML payload into normalized news items."""
    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out

    for item in root.findall(".//item")[:10]:
        title = _clean_text(item.findtext("title"), max_len=140)
        if not title:
            continue
        desc = _clean_text(item.findtext("description"), max_len=190)
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        img = _extract_rss_image(item)
        out.append(
            {
                "news_title": title,
                "caption": desc or title,
                "source": source_name,
                "article_url": link if link.startswith("https://") else None,
                "image_url": img,
                "published_at": pub or None,
                "hint_category": default_category,
                "provider": "rss",
            }
        )
    return out


async def _fetch_rss_feed(
    client: httpx.AsyncClient,
    source_name: str,
    default_category: str,
    url: str,
) -> list[dict[str, Any]]:
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return []
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                rem = _MAX_FEED_BYTES - len(buf)
                if rem <= 0:
                    break
                buf.extend(chunk[:rem])
                if len(buf) >= _MAX_FEED_BYTES:
                    break
            return parse_rss_xml(bytes(buf), source_name, default_category)
    except Exception:  # noqa: BLE001
        return []


async def _fetch_gdelt(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        resp = await client.get(_GDELT_URL)
        if resp.status_code != 200:
            return []
        data = resp.json()
        out: list[dict[str, Any]] = []
        for art in data.get("articles") or []:
            title = _clean_text(art.get("title"), max_len=140)
            img = _valid_https_image(art.get("socialimage"))
            if not title or not img:
                continue
            domain = str(art.get("domain") or "News").removeprefix("www.")
            source = domain.split(".")[0].upper() if len(domain.split(".")[0]) <= 4 else domain.split(".")[0].title()
            url = str(art.get("url") or "").strip()
            out.append(
                {
                    "news_title": title,
                    "caption": f"Reported by {source} · Live global wire coverage.",
                    "source": source,
                    "article_url": url if url.startswith("https://") else None,
                    "image_url": img,
                    "published_at": art.get("seendate"),
                    "hint_category": "General",
                    "provider": "gdelt",
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


async def _fetch_currents(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    api_key = os.environ.get("CURRENTS_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = await client.get(
            "https://api.currentsapi.services/v1/latest-news",
            params={"language": "en", "apiKey": api_key},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        out: list[dict[str, Any]] = []
        for art in (data.get("news") or [])[:12]:
            title = _clean_text(art.get("title"), max_len=140)
            if not title:
                continue
            img = _valid_https_image(art.get("image"))
            desc = _clean_text(art.get("description"), max_len=190)
            url = str(art.get("url") or "").strip()
            cats = art.get("category") or []
            out.append(
                {
                    "news_title": title,
                    "caption": desc or title,
                    "source": str(art.get("author") or "Currents").strip()[:40] or "Currents",
                    "article_url": url if url.startswith("https://") else None,
                    "image_url": img,
                    "published_at": art.get("published"),
                    "hint_category": str(cats[0]).title() if cats else "General",
                    "provider": "currents",
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


async def _fetch_wikimedia_image(client: httpx.AsyncClient, topic: str) -> str | None:
    if topic in _wiki_image_cache:
        return _wiki_image_cache[topic]
    try:
        resp = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(topic, safe='_()')}"
        )
        if resp.status_code != 200:
            _wiki_image_cache[topic] = None
            return None
        data = resp.json()
        img = _valid_https_image(
            (data.get("originalimage") or {}).get("source")
            or (data.get("thumbnail") or {}).get("source")
        )
        _wiki_image_cache[topic] = img
        return img
    except Exception:  # noqa: BLE001
        _wiki_image_cache[topic] = None
        return None


def _infer_wiki_topic(text: str) -> str:
    low = (text or "").lower()
    for kw, topic in _WIKI_TOPIC_MAP:
        if kw in low:
            return topic
    return "Financial_market"


async def fetch_raw_news(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch and deduplicate raw news items across RSS + GDELT + Currents with 15m TTL."""
    global _raw_news_cache  # noqa: PLW0603
    now_m = time.monotonic()
    if not force_refresh and _raw_news_cache is not None and now_m < _raw_news_cache[0]:
        return _raw_news_cache[1]

    headers = {"User-Agent": "AlgoXenNewsCarousel/1.0 (+https://algoxen.example.com)"}
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers=headers) as client:
        tasks = [
            _fetch_rss_feed(client, src, cat, url) for src, cat, url in _RSS_FEEDS
        ]
        tasks.append(_fetch_gdelt(client))
        tasks.append(_fetch_currents(client))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    combined: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for res in results:
        if not isinstance(res, list):
            continue
        for item in res:
            norm = re.sub(r"[^a-z0-9]+", "", item["news_title"].lower())[:64]
            if not norm or norm in seen_titles:
                continue
            seen_titles.add(norm)
            combined.append(item)

    # Prefer items that already carry a crisp HTTPS newsroom photo.
    combined.sort(key=lambda x: (0 if x.get("image_url") else 1))
    _raw_news_cache = (now_m + CACHE_TTL_SECONDS, combined)
    return combined


def _score_market_match(news_item: dict[str, Any], ev: dict[str, Any]) -> float:
    n_text = f"{news_item.get('news_title', '')} {news_item.get('caption', '')}"
    e_text = f"{ev.get('title', '')} {ev.get('question', '')} {ev.get('category', '')}"
    nt = _tokens(n_text)
    et = _tokens(e_text)
    if not nt or not et:
        return 0.0
    overlap = len(nt & et)
    score = float(overlap) * 3.0

    ev_cat = (ev.get("category") or "").lower()
    hint_cat = (news_item.get("hint_category") or "").lower()
    if ev_cat and hint_cat and (ev_cat in hint_cat or hint_cat in ev_cat):
        score += 1.5
    for cat_key, kws in _CATEGORY_KEYWORDS.items():
        if cat_key in ev_cat and (nt & kws):
            score += 1.0
    return score


def _item_matches_filter(item: dict[str, Any], category: str | None, tag: str | None) -> bool:
    """Strictly match a news item to the requested category or tag."""
    cat_q = (category or "").strip().lower()
    tag_q = (tag or "").strip().lower()
    if cat_q in ("", "trending", "new", "all"):
        cat_q = ""
    if tag_q in ("", "all"):
        tag_q = ""
    if not cat_q and not tag_q:
        return True

    hint = (item.get("hint_category") or "").lower()
    hay = f"{hint} {item.get('news_title', '')} {item.get('caption', '')} {item.get('source', '')}".lower()
    hay_tokens = _tokens(hay)

    if cat_q:
        # Direct category match or keyword match for that category
        cat_ok = (cat_q in hint) or (hint in cat_q and bool(hint))
        if not cat_ok:
            for k, kws in _CATEGORY_KEYWORDS.items():
                if k in cat_q and (hay_tokens & kws):
                    cat_ok = True
                    break
        if not cat_ok and cat_q not in hay:
            return False

    if tag_q and tag_q not in hay:
        return False
    return True


async def build_news_carousel(
    active_events: list[dict[str, Any]],
    *,
    limit: int = 12,
    category: str | None = None,
    tag: str | None = None,
    raw_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Match live news items (photos + titles + captions) to active markets."""
    if not active_events:
        return []

    items = raw_items if raw_items is not None else await fetch_raw_news()
    if category or tag:
        items = [it for it in items if _item_matches_filter(it, category, tag)]
        if not items:
            return []

    slides: list[dict[str, Any]] = []
    per_event_counts: dict[str, int] = {}
    max_per_event = max(2, (limit // max(1, len(active_events))) + 1)

    for idx, item in enumerate(items):
        if len(slides) >= limit:
            break
        ranked = sorted(
            active_events,
            key=lambda ev: (
                _score_market_match(item, ev),
                -per_event_counts.get(ev["event_id"], 0),
                float(ev.get("volume") or 0),
            ),
            reverse=True,
        )
        chosen = None
        for cand in ranked:
            if per_event_counts.get(cand["event_id"], 0) < max_per_event:
                chosen = cand
                break
        if chosen is None:
            chosen = ranked[idx % len(ranked)]

        per_event_counts[chosen["event_id"]] = per_event_counts.get(chosen["event_id"], 0) + 1
        sid = hashlib.sha1(f"{item['news_title']}:{chosen['slug']}".encode()).hexdigest()[:12]
        slides.append(
            {
                "id": f"news-{sid}",
                "news_title": item["news_title"],
                "caption": item["caption"],
                "source": item["source"],
                "article_url": item.get("article_url"),
                "image_url": item.get("image_url"),
                "published_at": item.get("published_at"),
                "provider": item.get("provider", "rss"),
                "event_id": chosen["event_id"],
                "market_id": chosen.get("market_id"),
                "market_slug": chosen["slug"],
                "market_title": chosen["title"],
                "category": item.get("hint_category") or chosen.get("category") or "Markets",
                "yes_pct": chosen.get("yes_pct"),
                "volume": float(chosen.get("volume") or 0),
            }
        )

    # Wikimedia fallback (Source #4) fetched concurrently for any slide missing a photo.
    missing_img = [s for s in slides if not s.get("image_url")][:6]
    if missing_img and raw_items is None:
        headers = {"User-Agent": "AlgoXenNewsCarousel/1.0 (+https://algoxen.example.com)"}
        async with httpx.AsyncClient(timeout=3.0, headers=headers) as client:
            topics = [_infer_wiki_topic(f"{s['market_title']} {s['news_title']}") for s in missing_img]
            wiki_imgs = await asyncio.gather(
                *(_fetch_wikimedia_image(client, t) for t in topics),
                return_exceptions=True,
            )
            for s, img in zip(missing_img, wiki_imgs):
                if isinstance(img, str) and img:
                    s["image_url"] = img

    return slides
