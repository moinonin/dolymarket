# Live DexBuilder data

Dolymarket can display **live** prediction-market data straight from
`api.dexbuilder.com` — real markets, quotes, order books, candles and the
trade tape — without any DexBuilder account.

Open the **Live** tab in the main navigation (or use the *Live DexBuilder feed*
button on the Markets page).

## Historical and resolved markets

DexBuilder keeps its settled history: `status=closed` returns markets that have
already resolved, and `offset` walks back through it in pages of up to 100.

| Dolymarket filter | Upstream status |
|---|---|
| `active` (or `open`) | `active` |
| `resolved` (or `settled`, `historical`) | `closed` |
| `closed` | `closed` |
| *(empty)* | `closed` |

```bash
curl "http://localhost:8000/api/v4/prediction/live/markets?status=resolved&limit=50&offset=0"
curl "http://localhost:8000/api/v4/prediction/live/markets?status=resolved&limit=50&offset=2000"
```

The response carries the pagination cursor:

```json
{ "markets": [], "status": "closed", "offset": 2000, "limit": 50,
  "has_more": true, "next_offset": 2050, "source": "dexbuilder" }
```

### How the winner is derived

DexBuilder does not expose a `winner` field. It settles a closed market by
pricing the winning outcome at exactly `1` and the losing outcome at `0`, so
Dolymarket derives the result from the settlement prices:

- exactly one outcome priced `1` → that outcome is the winner
  (`winning_outcome_index`, `winning_outcome`)
- zero or several outcomes priced `1` → the market is closed but **not** settled
  cleanly, so no winner is reported

Active markets never report a winner.

In the UI, switch the Live page to **Resolved** (or **All closed**) and page
back with **Older →**; resolved cards show the outcome that won.

## What is live

| Surface | Upstream endpoint | Dolymarket route |
|---|---|---|
| Markets list | `GET /api/v4/prediction/markets` | `GET /api/v4/prediction/live/markets` |
| Market detail | `GET /api/v4/prediction/markets/{id}` | `GET /api/v4/prediction/live/markets/{id}` |
| Events | `GET /api/v4/prediction/events` | `GET /api/v4/prediction/live/events` |
| Order book | `GET /api/v4/prediction/tokens/{id}/order_book` | `GET /api/v4/prediction/live/tokens/{id}/order_book` |
| Price history | `GET /api/v4/prediction/tokens/{id}/price_history` | `GET /api/v4/prediction/live/tokens/{id}/price_history` |
| Candlesticks | `GET /api/v4/prediction/tokens/{id}/candlesticks` | `GET /api/v4/prediction/live/tokens/{id}/candlesticks` |
| Trade tape | `GET /api/v4/prediction/markets/{id}/trades` | `GET /api/v4/prediction/live/markets/{id}/trades` |
| Tags | `GET /api/v4/prediction/tags` | `GET /api/v4/prediction/live/tags` |
| Server clock | `GET /api/v4/prediction/time` | `GET /api/v4/prediction/live/time` |

`GET /api/v4/prediction/live/status` reports the integration state (upstream URL,
cache size, circuit breaker).

## No credentials required

DexBuilder serves every surface above **without** an API key. The HMAC signature
headers are only attached when `DEXBUILDER_API_SECRET` is configured, so a fresh
install shows live data out of the box.

The credential-gated namespace `/api/v4/dexbuilder/*` keeps its own contract and
answers `503 DEXBUILDER_NOT_CONFIGURED` until an API key is present.

## Read-only

Live markets are a **market data feed**, not a tradeable venue in this build:

- Live prices, books and prints come from DexBuilder.
- Orders can only be placed on the local (seeded) markets.
- Live views are labelled *read-only* so a quote is never mistaken for a
  tradeable instrument.

## Normalization rules

- Every upstream numeric is a string (`"0.028"`); it is parsed into `Decimal`
  before any derivation, and only converted to a JSON number at the edge.
- `mid_price = (best_bid + best_ask) / 2`.
- Upstream sends asks **descending** and bids **ascending**; Dolymarket
  normalizes both sides so the best price is first (matching the local order
  book contract).
- Outcome labels are localized upstream (`{"en": ..., "cn": ...}`); English is
  used.
- Market status is upper-cased (`active` → `ACTIVE`).

## Resilience

- Successful reads are cached for **10 seconds** so a page refresh does not
  hammer the upstream.
- After **3** consecutive failures a circuit breaker opens for **30 seconds**.
- If the upstream breaks while a value is cached, the stale value is served
  instead of an error.
- When the upstream is unreachable the routes answer
  `502 DEXBUILDER_UPSTREAM_UNAVAILABLE` and the UI shows an error banner while
  the rest of the app keeps working.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DEXBUILDER_API_BASE` | `https://api.dexbuilder.com` | Upstream base URL |
| `DEXBUILDER_API_KEY` | *(empty)* | Credentialed proxy namespace |
| `DEXBUILDER_API_SECRET` | *(empty)* | HMAC signing for private reads |
| `DEXBUILDER_TIMEOUT` | `10` | Upstream request timeout (seconds) |

## Known upstream gaps

| Upstream surface | Behaviour | Dolymarket handling |
|---|---|---|
| `tokens/{id}/price` | 404 | Derived from market detail / order book |
| `tokens/{id}/ticker` | 404 | Derived from market detail quotes |
| `tokens/prices` | empty `items` | Derived from the market list |
| `tokens/{id}/market` | 404 | Resolved locally from the token index |
| `markets/slug/{slug}` | 404 | Slug lookups resolve through the market list |
| `tokens/{id}/price_history` | 404 for unindexed tokens | Falls back to `candlesticks` |

## Private data (still blocked)

`usertrades`, `positions`, `account_book`, `assets`, `fee` and `claims/*` require
DexBuilder credentials **and** the official REST signing spec. See
[DexBuilder TODO](dexbuilder-todo.md) for the current status.
