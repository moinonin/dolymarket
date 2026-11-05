# Feature: DexBuilder integration — consume the documented API and implement the remaining surfaces

## Change type and operating rules

This is a brownfield change to an existing repository, not a new project. Read
`app/` and `frontend/src/` first and extend the modules in place. Do not
scaffold a new project, regenerate an existing file from the top, or add a
second `Base`, `User`, `FastAPI` instance, or duplicate route. Every endpoint
in `.githeri/baseline.json` must keep resolving after the change.

## Context

Dolymarket is a standalone prediction market platform in this repository
(FastAPI + SQLAlchemy async backend, React/TypeScript frontend, in-memory CLOB,
CTF settlement, WebSockets). The reference documentation in `predmarket/scraped/`
describes the Gatelabs DexBuilder API at `https://api.dexbuilder.com` with two
namespaces: `/api/v4/prediction/*` (and, for reference only,
`/api/v4/event_contracts/*`). Scope for this change is the **prediction market
only**: PerpDEX, Event Contracts and multi-product surfaces are explicitly out
of scope. The `event_contracts` documentation is retained as reference for a
later phase and is not implemented now. The application currently re-implements
a subset of the `prediction` namespace. The goal is to (a) consume the
documented DexBuilder prediction endpoints through a typed client and (b)
implement the remaining prediction surfaces locally so the platform reaches
parity with the documentation.

Existing pieces to extend:
- `app/api/v4/prediction/*` routers (public, orders, positions, resolution, ws, admin)
- `app/api/v1/` (auth, collateral, desks)
- `app/models/domain.py` (User, Market, OutcomeToken, Order, TradeFill, Position, Desk, ...)
- `app/services/collateral.py`, `app/engine/clob.py`
- `frontend/src/api/client.ts`, `frontend/src/pages/*`, `frontend/src/App.tsx`

All money columns use `Numeric(18,4)` and service code uses `Decimal`. No
binary floating point for balances, prices, fees, shares or caps.

## Goal

Reach parity with the DexBuilder documented API on two fronts:

1. **Consume** the documented endpoints. Add a server-side DexBuilder client
   (`app/services/dexbuilder.py`) that calls `https://api.dexbuilder.com` using
   a configurable base URL (`DEXBUILDER_API_BASE`, default
   `https://api.dexbuilder.com`) and an API key (`DEXBUILDER_API_KEY`), with
   HMAC-SHA256 request signing when `DEXBUILDER_API_SECRET` is set. Expose
   proxied read endpoints under `/api/v4/dexbuilder/*` so the frontend can
   source live market data, prices, order books, trades and positions from
   DexBuilder when configured, falling back to the local implementation when it
   is not.
2. **Implement the remaining surfaces locally** so every documented route
   exists in the application, whether or not DexBuilder credentials are set:
   - the missing `prediction` routes: `GET /tags`, `GET /tokens/prices`,
     `GET /usertrades`, `GET /positions/settled`, `GET /markets/slug/{slug}`;
   - the WebSocket channels `wss://.../ws/dex-builder/prediction` and
     `.../event-contracts` consumed by `frontend/src/api/reconnectingSocket.ts`
     with exponential backoff (1s to 30s, jitter 0-20%) and a snapshot resync
     after reconnect.

## Explicit non-goals

- No change to the matching engine, settlement, collateral or auth logic beyond
  what the new routes require.
- No pooled capital or custody changes.
- No new admin privileges beyond the existing `User.is_admin` flag.
- No removal of any existing route; the change is additive.

## Actors, roles and ownership boundaries

- **Visitor**: unauthenticated. May read public market data, tags, prices,
  order books and public WebSocket streams. Must receive HTTP 401 on mutating
  routes.
- **Authenticated trader**: may submit and cancel only their own orders, read
  only their own positions, trades and settled positions, and receive only their
  own private WebSocket fills.
- **Admin**: `User.is_admin = True`. May create events and markets and close
  markets. Any other caller receives HTTP 403 `ADMIN_REQUIRED`.

Ownership rules (mandatory):
- A trader may view, cancel or redeem only their own orders, positions and
  trades. A request for another user's resource must be rejected with HTTP 403
  and must not disclose the target's existence; an unknown id returns HTTP 404.
- Unauthenticated requests to private endpoints return HTTP 401.

## Domain model

No new core tables are required. Reuse `Event`, `Market`, `OutcomeToken`,
`Order`, `TradeFill`, `Position`, `CollateralAccount`. Add a thin
`DexBuilderConfig` settings object (env-driven, no table) holding
`api_base`, `api_key`, `api_secret`, `ws_url` and `enabled`.

## API surface

All routes below are added. Existing routes keep their paths and shapes.

Public, no authentication, under `/api/v4/prediction/`:
- `GET /events` — list events; query `status`, `category`, `tag`, `limit`, `cursor`.
- `GET /events/{event_id}` — event detail with markets.
- `GET /events/slug/{slug}` — event by slug with markets.
- `GET /markets` — list markets; query `status`, `category`, `tag`, `limit`.
- `GET /markets/{market_id}` — market detail with tokens.
- `GET /markets/slug/{slug}` — market by slug with tokens.
- `GET /tags` — distinct tags across events.
- `GET /tokens/{token_id}/order_book` — L2 depth snapshot.
- `GET /tokens/{token_id}/price` — last price.
- `GET /tokens/{token_id}/price_history` — OHLCV series.
- `GET /tokens/{token_id}/ticker` — BBO and 24h stats.
- `GET /tokens/prices` — bulk prices for a list of token ids (query `ids`).

Authenticated, under `/api/v4/prediction/`:
- `GET /orders` — the caller's orders; query `market_id`, `status`, `limit`.
- `POST /orders` — submit an order (existing, unchanged).
- `DELETE /orders/{order_id}` — cancel one of the caller's open orders.
- `DELETE /orders` — batch cancel by `market_id` or `condition_id`.
- `GET /positions` — the caller's positions.
- `GET /positions/settled` — the caller's settled positions.
- `POST /positions/merge`, `POST /positions/split` — CTF merge and divide.
- `POST /positions/{position_id}/redeem` — redeem a winning position.
- `GET /usertrades` — the caller's trade history.
- `GET /ws/public`, `GET /ws/private` — WebSocket channels (existing).

Admin, under `/api/v4/prediction/admin/`:
- `POST /events`, `POST /markets`, `POST /markets/{market_id}/close`.

Proxied read endpoints under `/api/v4/dexbuilder/` (prediction namespace only):
- `GET /markets`, `GET /markets/{id}`, `GET /markets/slug/{slug}`
- `GET /tokens/{id}/order_book`, `/price`, `/price_history`, `/ticker`, `/prices`
- `GET /events`, `GET /events/{id}`, `GET /events/slug/{slug}`
- `GET /tags`, `GET /usertrades`, `GET /positions`, `GET /positions/settled`
These forward to DexBuilder when `DEXBUILDER_API_KEY` is set and return
HTTP 503 `DEXBUILDER_NOT_CONFIGURED` otherwise. They never mutate local state.

WebSocket consumption:
- `frontend/src/api/reconnectingSocket.ts` connects to
  `wss://broker.dexbuilder.com/ws/dex-builder/prediction` when
  `VITE_DEXBUILDER_WS_URL` is set, with exponential backoff (1s to 30s, jitter
  0-20%) and a snapshot resync after reconnect.

## Frontend requirements

- `frontend/src/pages/TagsPage.tsx` listing tags and the markets for a tag.
- `frontend/src/pages/UserTradesPage.tsx` showing the caller's trade history.
- `frontend/src/pages/SettledPositionsPage.tsx`.
- `frontend/src/pages/MarketDetailPage.tsx` consuming bulk prices from
  `/tokens/prices` and the order book from `/tokens/{id}/order_book`.
- Wire all four into the hash router in `frontend/src/App.tsx` with nav
  entries; anonymous visitors see a sign-in call to action on private views.
- All views read through the typed client in `frontend/src/api/client.ts`; no
  hardcoded `localhost` or `127.0.0.1` URLs; no mock data arrays; every view
  handles loading, empty and error states.
- Tailwind v4 and lucide-react; browser title `dolymarket`.

## Money, ledger and concurrency rules

- Bulk price and position values use `Decimal` / `Numeric(18,4)`; no binary
  floating point for balances, prices, fees, shares or caps.
- Proxied DexBuilder responses are validated against the local Pydantic schemas
  before being returned; an invalid payload returns HTTP 502
  `DEXBUILDER_BAD_RESPONSE`.
- Local order submission keeps the existing row-level lock and idempotency key
  behavior unchanged, and balance conservation (sum of debits equals sum of
  credits) holds across every proxied and local mutation.

## Regulatory and disclosure constraints

- Market data sourced from DexBuilder is labelled "Source: DexBuilder" in the UI.
- No trading advice, no projected returns, no performance-based incentives.
- Existing auth, collateral, order, position and settlement behavior is unchanged.

## Environment variables

Document in `.env.example` and README:
- `DEXBUILDER_API_BASE` (default `https://api.dexbuilder.com`)
- `DEXBUILDER_API_KEY`
- `DEXBUILDER_API_SECRET`
- `DEXBUILDER_WS_URL` (default `wss://broker.dexbuilder.com/ws/dex-builder/prediction`)
- `VITE_DEXBUILDER_WS_URL`

## Automated verification

Add automated pytest integration tests exercising the actual API routes and
the real database session, covering both allowed and rejected cases:
- `tests/test_dexbuilder_parity.py`: every route in the `endpoints` list
  returns the documented status; the proxied routes return 503 when
  `DEXBUILDER_API_KEY` is unset and 200 with a mocked DexBuilder response
  when it is set.
- (out of scope for this change: the `event_contracts` namespace, PerpDEX and
  multi-product surfaces; the documentation is retained as reference.)
- `tests/test_bulk_prices.py`: `GET /tokens/prices?ids=...` returns one entry
  per requested id and 422 on an empty list.
- `tests/test_tags.py`: `GET /tags` returns distinct tags.
- `tests/test_settled_positions.py`: `GET /positions/settled` returns only
  settled positions for the caller.
- `tests/test_usertrades.py`: `GET /usertrades` returns only the caller's
  trades.
- `tests/test_route_baseline.py` still passes (the change is additive).

## Definition of done

1. Every test above is present as an automated pytest integration test and all
   automated tests pass, including the pre-existing suite, with zero failures.
2. `pytest -q` passes and `ruff check app tests --select F821,F811,E9` reports
   no findings.
3. The application starts successfully from `app/main.py` with no import error
   and no background server process is left running.
4. `cd frontend && npm run build` completes with zero TypeScript errors and a
   successful bundle.
5. Contract verification passes: the new routes are declared in the Githeri
   spec and report as matched, with no missing route.
6. All money, price, fee, share and cap values use Decimal and Numeric columns.
7. Existing auth, order, collateral, position, settlement and desk behavior is
   unchanged.
8. The new environment variables are documented in `.env.example` and README.