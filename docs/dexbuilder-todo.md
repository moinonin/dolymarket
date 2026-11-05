# DexBuilder integration — TODO and upstream API status

## Live data is wired (no credentials needed)

The public DexBuilder prediction surfaces are consumed and displayed today.

| Surface | Upstream | Dolymarket route | State |
|---|---|---|---|
| Markets list | `GET /api/v4/prediction/markets` | `GET /api/v4/prediction/live/markets` | done (active + closed history via `status`/`offset`) |
| Market detail | `GET /api/v4/prediction/markets/{id}` | `GET /api/v4/prediction/live/markets/{id}` | done |
| Events | `GET /api/v4/prediction/events` | `GET /api/v4/prediction/live/events` | done |
| Order book | `GET /api/v4/prediction/tokens/{id}/order_book` | `GET /api/v4/prediction/live/tokens/{id}/order_book` | done |
| Price history | `GET /api/v4/prediction/tokens/{id}/price_history` | `GET /api/v4/prediction/live/tokens/{id}/price_history` | done (candlestick fallback) |
| Candlesticks | `GET /api/v4/prediction/tokens/{id}/candlesticks` | `GET /api/v4/prediction/live/tokens/{id}/candlesticks` | done |
| Trade tape | `GET /api/v4/prediction/markets/{id}/trades` | `GET /api/v4/prediction/live/markets/{id}/trades` | done |
| Tags | `GET /api/v4/prediction/tags` | `GET /api/v4/prediction/live/tags` | done |
| Server time | `GET /api/v4/prediction/time` | `GET /api/v4/prediction/live/time` | done |

Frontend: **Live** nav entry (`#/live`) with market list, quotes, order book,
price chart and trade tape. See [Live DexBuilder data](live-data.md).

## Upstream endpoint status (probed live against api.dexbuilder.com)

### Streaming today (public, no auth)

| Endpoint | Status | Notes |
|---|---|---|
| GET /api/v4/prediction/markets | 200 | live markets; `status=active` for open markets, `status=closed` for the resolved history (`offset` pages back) |
| GET /api/v4/prediction/markets/{id} | 200 | best_bid/ask, last_trade_price |
| GET /api/v4/prediction/markets/{id}/trades | 200 | public trade history |
| GET /api/v4/prediction/tokens/{id}/order_book | 200 | real asks/bids |
| GET /api/v4/prediction/tokens/{id}/candlesticks | 200 | K-line (OHLCV) |
| GET /api/v4/prediction/tokens/{id}/price_history | 200 | needs interval + millisecond from/to (<=14 days) |
| GET /api/v4/prediction/tags | 200 | real tags |
| GET /api/v4/prediction/time | 200 | server time (ms) |
| GET /api/v4/prediction/events | 200 | localized titles + tag objects |
| GET /api/v4/prediction/tokens/prices | 200 | returns {"items": []} even for valid ids (upstream gap) |
| GET /api/v4/prediction/tokens/{id}/price | 404 | not implemented upstream — use market detail / order book |
| GET /api/v4/prediction/tokens/{id}/ticker | 404 | not implemented upstream — use market detail / order book |
| GET /api/v4/prediction/tokens/{id}/market | 404 | not implemented upstream |
| GET /api/v4/prediction/markets/slug/{slug} | 404 | not implemented upstream |

### Auth-gated (require an HMAC `Timestamp` header — blocked on credentials)

| Endpoint | Status | Blocker |
|---|---|---|
| GET /api/v4/prediction/usertrades | 400 | Missing Timestamp header |
| GET /api/v4/prediction/positions/settled | 400 | Missing Timestamp header |
| GET /api/v4/prediction/positions/{id} | 400 | Missing Timestamp header |
| GET /api/v4/prediction/assets | 400 | Missing Timestamp header |
| GET /api/v4/prediction/account_book | 400 | Missing Timestamp header |
| GET /api/v4/prediction/fee | 400 | Missing Timestamp header |
| GET /api/v4/prediction/claims/available | 400 | Missing Timestamp header |
| POST /api/v4/prediction/claims | 400 | Missing Timestamp header |

### Blockers
1. No DexBuilder API credentials (DEXBUILDER_API_KEY / DEXBUILDER_API_SECRET) in this environment.
2. REST HMAC signing scheme (header names + signed message format) is not documented in the scraped material — only the WebSocket auth (`t`, `key`, `sign`) is. Our `_sign` now sends the canonical `Timestamp` header plus `key`/`sign` and the `X-DB-*` aliases, with the query string included in the signed message, but the exact upstream scheme is still unverified.
3. Upstream gaps (not our bug): single-token `/price` and `/ticker`, bulk `/tokens/prices` (empty), `/tokens/{id}/market`, `/markets/slug/{slug}`, and `/tokens/{id}/price_history` returning 404 for unindexed tokens.

## TODO
- [x] Obtain live public DexBuilder data without credentials and display it (markets, quotes, books, candles, trades, tags, time).
- [x] Historical / resolved markets: `status=resolved` maps to upstream `closed`, `offset` pages back through the history, and the winner is derived from the settlement prices.
- [x] Implement the remaining backend surfaces: tags, bulk prices, user trades, settled positions, time, trades, candlesticks, token market.
- [x] Frontend: TagsPage, UserTradesPage, SettledPositionsPage, MarketDetailPage, Live markets + live market detail, dexbuilder proxy client methods and nav wiring.
- [ ] Obtain DexBuilder API credentials and the official REST HMAC spec; verify usertrades/positions/assets/account_book/fee/claims end-to-end.
- [ ] Admin UI for creating events/markets and reviewing Pro Desks.
- [ ] Verify WebSocket streaming end-to-end against broker.dexbuilder.com (the client currently reads `VITE_WS_URL`; `VITE_DEXBUILDER_WS_URL` is unused).
- [ ] Route live markets into the trade ticket once upstream order placement is authenticated.
