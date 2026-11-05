# DexBuilder integration — TODO and upstream API status

## Upstream endpoint status (probed live against api.dexbuilder.com)

### Streaming today (public, no auth)

| Endpoint | Status | Notes |
|---|---|---|
| GET /api/v4/prediction/markets | 200 | live markets |
| GET /api/v4/prediction/markets/{id} | 200 | best_bid/ask, last_trade_price |
| GET /api/v4/prediction/markets/{id}/trades | 200 | public trade history |
| GET /api/v4/prediction/tokens/{id}/order_book | 200 | real asks/bids |
| GET /api/v4/prediction/tokens/{id}/candlesticks | 200 | K-line (OHLCV) |
| GET /api/v4/prediction/tokens/{id}/price_history | 200 | needs interval + from/to (<=14 days) |
| GET /api/v4/prediction/tags | 200 | real tags |
| GET /api/v4/prediction/time | 200 | server time |
| GET /api/v4/prediction/tokens/prices | 200 | returns {"items": []} even for valid ids (upstream gap) |
| GET /api/v4/prediction/tokens/{id}/price | 404 | not implemented upstream — use market detail / order book |
| GET /api/v4/prediction/tokens/{id}/ticker | 404 | not implemented upstream — use market detail / order book |
| GET /api/v4/prediction/tokens/{id}/market | 404 | not implemented upstream |
| GET /api/v4/prediction/markets/slug/{slug} | 404 | not implemented upstream |

### Auth-gated (require HMAC Timestamp header — blocked on credentials)

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
2. REST HMAC signing scheme (header names + signed message format) is not documented in the scraped material — only the WebSocket auth (`t`, `key`, `sign`) is. Our `_sign` uses a guessed scheme (`X-DB-KEY`/`X-DB-SIGN`/`X-DB-TIMESTAMP`, message `{timestamp}{method}{path}{body}`) which is unverified.
3. Upstream gaps (not our bug): single-token `/price` and `/ticker`, bulk `/tokens/prices` (empty), `/tokens/{id}/market`, `/markets/slug/{slug}`.

## TODO
- [ ] Obtain DexBuilder API credentials and the official REST HMAC spec; correct `_sign` and verify usertrades/positions/assets/account_book/fee/claims end-to-end.
- [ ] Implement the remaining backend surfaces: markets/{id}/trades (done locally), positions/{id}, positions/{id}/close, assets, account_book, fee, claims/*, time, candlesticks.
- [ ] Frontend: TagsPage, UserTradesPage, SettledPositionsPage, MarketDetailPage (bulk prices + order book), plus dexbuilder proxy client methods and nav wiring.
- [ ] Admin UI for creating events/markets and reviewing Pro Desks.
- [ ] Verify WebSocket streaming end-to-end against broker.dexbuilder.com.