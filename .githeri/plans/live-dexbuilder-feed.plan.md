# COMMAND_RUNWAY: live-dexbuilder-feed

# Feature
**Name:** live-dexbuilder-feed
**Purpose:** Pull the public DexBuilder prediction data we already receive, normalize it and display it in the Dolymarket UI.
**Reference Specification:** `.githeri/specs/live-dexbuilder-feed.spec.yaml`
**Expected Deliverables:**
- `app/services/live_data.py` — normalizers, TTL cache, circuit breaker.
- `app/api/v4/prediction/live.py` — 10 read-only live routes.
- `app/api/v4/dexbuilder/proxy.py` — `/time`, `/tokens/{id}/candlesticks`, `/markets/{id}/trades`, price-history params.
- `frontend/src/pages/LiveMarketsPage.tsx`, `frontend/src/pages/LiveMarketDetailPage.tsx`, client methods and nav wiring.
- `tests/test_live_data.py` — hermetic upstream tests (no network).

**Dependencies:**
- `fastapi`
- `httpx`
- `pydantic`

**Assumptions:**
- DexBuilder serves the public prediction surfaces without credentials.
- Credentialed upstream reads stay blocked on the official REST HMAC spec.

---

# Global Success Criteria
- Live upstream data is reachable without any DexBuilder credential.
- The `/api/v4/dexbuilder` proxy namespace keeps its 503 `DEXBUILDER_NOT_CONFIGURED` contract.
- Money, price and share values are parsed and derived with `Decimal`.
- Upstream failures surface as HTTP 502 `DEXBUILDER_UPSTREAM_UNAVAILABLE` and a UI error state.
- `pytest`, `ruff`, `githeri verify` and `npm run build` all pass.

---

# Phase 1 — Services
1. Extend `DexBuilderConfig` with `public_reads` (base URL present) and a request timeout.
2. Extend `DexBuilderClient` so the HMAC headers are attached only when a secret exists; send the canonical `Timestamp` header plus `key`/`sign` and the `X-DB-*` aliases; include the query string in the signed message.
3. Add client methods for `time`, `candlesticks`, `price_history(interval, from, to)` and `market_trades`.
4. Create `app/services/live_data.py` with Decimal helpers, normalizers (`market`, `event`, `tags`, `order_book`, `trades`, `candles`), a 10 second TTL cache, stale-on-error behaviour and a 3 failure / 30 second circuit breaker.

# Phase 2 — Routes
1. Add `app/api/v4/prediction/live.py` with the live status, markets, market detail, events, tags, time, order book, price history, candlesticks and trade tape routes; mount it in `app/main.py`.
2. Extend the proxy router with `/time`, `/tokens/{token_id}/candlesticks`, `/markets/{market_id}/trades`, forwarded price-history parameters and repeated `token_ids` bulk prices.

# Phase 3 — Frontend
1. Add the live client methods and domain types to `frontend/src/api/client.ts`.
2. Add `LiveMarketsPage` (search, auto refresh, loading / empty / error states) and `LiveMarketDetailPage` (quotes, order book ladder, price chart, trade tape, read-only notice).
3. Wire the `#/live` and `#/live/market/{id}` hash routes and the `Live` nav entry; link the live feed from the Markets hero.

# Phase 4 — Verification
1. `tests/test_live_data.py` with a mocked upstream (httpx MockTransport): normalizers, cache, circuit breaker, stale fallback, history fallback, route payloads and the 502 path.
2. `pytest -q`, `ruff check app tests --select F821,F811,E9`, `githeri verify`, `npm run build`, `mkdocs build --strict`.
3. Update `docs/dexbuilder-todo.md` and add `docs/live-data.md`.
