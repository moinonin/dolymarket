# Market Details, Clarity & Microstructure

Dolymarket surfaces two complementary market views: **Local / Community Markets** (`#markets`, `#event/<slug>`, `#market/<id>`) and **Live DexBuilder Markets** (`#live`, `#live/market/<id>`).

---

## 1. Official vs Community Markets (`#markets`)

`MarketsPage` (`frontend/src/pages/MarketsPage.tsx`) distinguishes market tiers via status badges:
- **Official Markets**: Platform-curated events (`tier: OFFICIAL`) with CLOB books and optional Pro Desk market makers.
- **Community Markets** (`Community` badge): User-created markets (`POST /api/v4/prediction/community/markets`) subject to prohibited-category checks and mandatory `resolution_criteria`.
  - **`Unfunded` badge**: Newly created community markets start in `UNFUNDED` status until at least **$10.00 USDC** is funded (`POST /api/v4/prediction/community/markets/{id}/fund`), which automatically seeds an `AmmPool` and activates trading (`ACTIVE`).
  - **Optional AGX Bond**: Creators may optionally pass `bond_with_agx: true` to lock the complementary 1,000 AGX market bond (`app/services/agx.py`).

---

## 2. Oracle Clarity Score (`#market/<id>`)

Every market payload (`app/api/v4/public.py`) includes a pre-trade `clarity` object computed by `compute_clarity_score()` (`app/services/oracle.py`) on a `0–100` scale (`25` points each):
1. **Authoritative Source**: Cites a URL (`https://`), `oracle_feed`, or recognized source (`Gate`, `CoinGecko`, `Pyth`, `Chainlink`, `Reuters`, `SEC`, `BLS`, `Fed`, etc.).
2. **Unambiguous Predicate**: Contains explicit binary/numeric comparison wording (`resolves yes`, `>=`, `above`, `below`, numeric threshold).
3. **Time / Window Bounded**: Has `end_date` or explicit UTC/date deadline.
4. **Non-Subjective Criteria**: At least 35 characters with no subjective weasel words (`maybe`, `vibes`, `discretion`, `tbd`).

`MarketDetailPage` (`frontend/src/pages/MarketDetailPage.tsx`) renders:
- **`Oracle Clarity: HIGH | MEDIUM | LOW (score/100)`** badge (hover tooltip shows any missing-rule `flags`).
- **`Feed: <provider>:<symbol>`** badge when `oracle_feed` is attached.
- Full `resolution_criteria` text directly under the market header.

---

## 3. Microstructure Telemetry Strip (`#market/<id>`)

Above the order book on `MarketDetailPage`, three live telemetry cards show execution quality:
- **Bid-Ask Spread**: `(bestAsk - bestBid) × 100` in cents (`¢`).
- **`$100` Buy Slippage**: Walks `book.asks` up to `$100` notional to compute VWAP impact in basis points (`+X bps`) over `bestAsk`.
- **Toxicity Shield (`EWI`)**: Live `fear_greed_service` regime (`STABLE` / `ELEVATED` / `CRITICAL`) and Early Warning Index (`ewi`).

---

## 4. Event & Live Market Components

- **Event Detail (`#event/<slug>`)**: Multi-outcome probability bars, `OrderBookLadder`, `RecentTrades`, 1m/5m/1h price chart, and `TradeTicket`.
- **Live Market Detail (`#live/market/<id>`)**: Streams real-time depth, BBO, and trades over `/api/v4/prediction/live/ws` (with REST polling fallback) and pairs with `LiveTradeTicket` for DexBuilder broker orders.
