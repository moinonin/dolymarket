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

### Auth-gated (signed with the official HMAC-SHA512 scheme)

| Endpoint | Status | Blocker |
|---|---|---|
| GET /api/v4/prediction/usertrades | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/positions | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/positions/settled | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/assets | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/account_book | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/fee | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| GET /api/v4/prediction/claims/available | 401 | `INVALID_KEY` — the configured key is not registered upstream |
| POST /api/v4/prediction/claims | 401 | `INVALID_KEY` — the configured key is not registered upstream |

The signing scheme is no longer guesswork: the upstream publishes it and we
implement it exactly — headers `KEY`, `Timestamp` (unix seconds) and `SIGN`,
with the signed message
`METHOD\nPATH\nQUERY\nHexEncode(SHA512(body))\nTIMESTAMP` signed with
HMAC-SHA512. See [DexBuilder authentication](dexbuilder-auth.md).

The upstream validates the key **before** the signature, so `INVALID_KEY`
means the key itself is unknown to DexBuilder (a wrong signature answers
`INVALID_SIGNATURE`). Check the key against the upstream account console.

### Blockers
1. The configured API key is rejected upstream with `INVALID_KEY`, so every
   credentialed read (usertrades, positions, assets, account book, fee,
   claims) stays unavailable. A valid **prediction markets** key for
   `api.dexbuilder.com` is required — a builder-console key or a key from
   another product is not accepted.
2. Upstream gaps (not our bug): single-token `/price` and `/ticker`, bulk `/tokens/prices` (empty), `/tokens/{id}/market`, `/markets/slug/{slug}`, and `/tokens/{id}/price_history` returning 404 for unindexed tokens.
3. The websocket broker (`wss://broker.dexbuilder.com/ws/dex-builder/prediction`) answers HTTP 503 for every channel, public ones included, so the streaming path cannot be verified against the live infrastructure yet (the bridge itself is verified against a local fake broker).

## TODO
- [x] Obtain live public DexBuilder data without credentials and display it (markets, quotes, books, candles, trades, tags, time).
- [x] Historical / resolved markets: `status=resolved` maps to upstream `closed`, `offset` pages back through the history, and the winner is derived from the settlement prices.
- [x] Implement the remaining backend surfaces: tags, bulk prices, user trades, settled positions, time, trades, candlesticks, token market.
- [x] Frontend: TagsPage, UserTradesPage, SettledPositionsPage, MarketDetailPage, Live markets + live market detail, dexbuilder proxy client methods and nav wiring.
- [x] Implement the official REST signing scheme (HMAC-SHA512 over `METHOD\nPATH\nQUERY\nSHA512(body)\nTIMESTAMP`) and report upstream credential rejection as `DEXBUILDER_UPSTREAM_UNAUTHORIZED` with the upstream label.
- [x] Add a credential diagnostic (`GET /api/v4/prediction/live/auth`) that never exposes the key or the secret.
- [ ] Obtain a valid DexBuilder prediction-markets API key and verify usertrades/positions/assets/account_book/fee/claims end-to-end (currently blocked by `INVALID_KEY`).
- [x] Admin console: create events and markets, close markets, review Pro Desks and audit copy jobs (admin-only routes, `is_admin` exposed to the client).
- [x] Copy-job history view for the trader (Activity) and for admins (console tab).
- [x] WebSocket bridge: the backend owns the upstream protocol and translates it into the Dolymarket envelope (`/api/v4/prediction/live/ws`), the live market page streams depth/bbo/trades and keeps REST polling as the fallback (`VITE_DEXBUILDER_WS_URL` is gone — the broker url is server-side only).
- [ ] Verify WebSocket streaming end-to-end against broker.dexbuilder.com (the bridge is implemented and tested against a local fake broker; the live broker still answers 503).
- [ ] Once a working credential is obtained: route upstream live markets into the trade ticket, migrate trading to upstream order placement, and purge the local seeded/demo market universe (the Live tab already shows the real upstream markets; the main Markets tab keeps seeded markets until then to avoid duplicating read-only rows).
- [ ] Live trading wallet layer (not started): replace the simulated `CollateralAccount` ledger with a real on-chain flow — add wallet connection (wagmi / viem / ethers + MetaMask, WalletConnect, Coinbase Wallet), read USDC balances from the on-chain contract, sign deposits/withdrawals/settlements, and gate order placement on a connected wallet. DexBuilder does not provide a custodial wallet; the user's own crypto wallet is the source of funds.

### Environment & configuration gaps (audit 2026-11-06)

- [ ] Set `JWT_SECRET` in `.env` — unset, the code falls back to a hardcoded public secret (`app/core/security.py`), so session tokens are forgeable by anyone who reads this repo. Also resolve the `.env.example` mismatch: `JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` are documented but the code hardcodes HS256 and a 24h TTL.
- [ ] Set `DATABASE_URL` in `.env` — the default is in-memory SQLite (`app/db/session.py`), so every backend restart wipes accounts, orders, positions, and the demo seed. Minimum: `sqlite+aiosqlite:///./dolymarket.db`; Postgres for production.
- [ ] Configure OAuth providers — `GOOGLE_*`, `MICROSOFT_*`, `APPLE_*` are absent, so every federated sign-in button renders disabled. Set `OAUTH_REDIRECT_BASE` / `OAUTH_FRONTEND_CALLBACK` once frontend and API stop sharing an origin.
- [ ] WebAuthn origin parity — `WEBAUTHN_ORIGIN(S)` are pinned to `localhost:8000`; passkeys fail on any other origin (127.0.0.1, LAN IP, tunnels). Add each new access origin to `WEBAUTHN_ORIGINS`. (`WEBAUTHN_RP_NAME` unset — cosmetic default.)
- [ ] Hygiene: never commit `.env` — it holds live DexBuilder credentials plus agent-tooling keys (`GEMINI_API_KEY`, `HF_TOKEN`, `NVIDIA_API_KEY`, `NOUSRESEARCH_API_KEY`, `GITHERI_API_KEY`) that nothing in `app/` reads.
- [ ] Fix the image-generation OpenAI key in the agent provider config (not app `.env`) — currently blocks generating the cinematic hero backdrop; the homepage hero ships the CSS + canvas fallback.
