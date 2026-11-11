# MISSION BRIEF: Production Full-Stack Prediction Market Platform (Polymarket & DexBuilder Architecture)

You are tasked with engineering a production-grade, end-to-end Prediction Market web application modelled after Polymarket and DexBuilder Event Markets architecture.

The application utilizes a hybrid execution and settlement model:
1. **Off-Chain High-Performance CLOB (Central Limit Order Book)**: Low-latency in-memory / Redis order placement, cancellation, matching with price-time priority, and continuous price formation.
2. **Conditional Token Framework (CTF) & Settlement Simulation**: Outcome share minting/burning, collateral locking (USDC/USDT), atomic outcome splitting/merging, and optimistic oracle resolution (UMA Optimistic Oracle pattern with proposal bond and dispute window).
3. **Real-Time Streaming**: High-throughput public & private WebSocket channels for orderbook depth, tickers, trade executions, and private user order fills.

---

## 1. CONTEXT, TECH STACK & ARCHITECTURAL CONSTRAINTS

### 1.1 Technology Stack
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (asyncio with `asyncpg` for PostgreSQL, `aiosqlite` for hermetic test execution), Pydantic v2 for strict schema validation.
- **Frontend**: Vite React 18/19, TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`), Lucide React icons, Lightweight Charts (or TradingView canvas) for OHLCV candlestick and probability curves.
- **Authentication & Cryptography**: Native `bcrypt` (`bcrypt.hashpw`) for password hashing and HMAC-SHA256 for signed API key authentication. **Never use unmaintained `passlib`**.
- **Real-Time Streaming**: Native FastAPI WebSocket server with pub/sub connection manager and client heartbeat ping/pong (30s interval).

### 1.2 Strict Operational & Agent Guidelines
- **Portability**: Never hardcode local user directory paths or `.venv/bin/` paths in scripts, plans, or tests.
- **Zero Hardcoded Localhost**: Never hardcode `http://localhost:8000` inside frontend components; use type-safe API client with relative environment fallback (`import.meta.env.VITE_API_URL || ''`).
- **Static Frontend Verification**: Never execute long-running dev servers (`npm run dev`). Verify frontend using `cd frontend && npm run build` (0 TypeScript errors, clean exit code 0).
- **Hermetic Testing**: Automated tests must run hermetically without external cloud dependencies or live blockchain networks.

---

## 2. END USERS, ROLES & STRICT RESOURCE BOUNDARIES

### 2.1 User Roles
1. **Anonymous Guest**: Public read-only access to market discovery, event specifications, L2 orderbook depth, price tickers, and public WebSocket streams.
2. **Authenticated Trader**: Can manage collateral balance (deposit/withdraw simulation), submit and cancel limit/market orders, inspect personal portfolio, receive private WebSocket execution fills, and claim winning outcome payouts.
3. **Market Admin / Oracle Proposer**: Can create events/markets, propose market resolution outcomes by posting a bond, and initiate dispute resolutions.

### 2.2 Strict Ownership & Multi-User Isolation Boundary
- Authenticated traders may view, submit, and cancel **only their own** orders, trades, and position records.
- Any request attempting to inspect, cancel, or redeem another user's order or position must be rejected with **HTTP 403 Forbidden** (or **HTTP 404 Not Found**) without disclosing sensitive resource existence.
- Unauthenticated requests to private endpoints must be rejected with **HTTP 401 Unauthorized**.

---

## 3. CORE DOMAIN CONCEPTS & BUSINESS INVARIANTS

### 3.1 Event vs. Market Hierarchy
- **Event**: Top-level parent grouping (e.g., "US Presidential Election 2028", "Fed Interest Rate Decision"). Contains `id` (UUID), `slug` (unique string), `title`, `description`, `category` (`Politics`, `Crypto`, `Sports`, `Macro`, `Pop Culture`, `Tech`), `tags` (JSON array), `status` (`ACTIVE`, `CLOSED`, `RESOLVED`), `start_date`, `end_date`, and aggregate `volume` (Decimal).
- **Market**: Specific tradable question under an Event (e.g., "Will Candidate X win?"). Contains `id` (UUID), `event_id` (FK), `condition_id` (unique hex string), `question`, `outcomes` (JSON array, e.g. `["YES", "NO"]`), `tick_size` (Decimal, default `0.01`), `min_order_size` (Decimal, e.g. `5.0` shares), `status` (`ACTIVE`, `SUSPENDED`, `CLOSED`, `IN_RESOLUTION`, `DISPUTED`, `RESOLVED`), `neg_risk` (bool), and `winning_outcome_index` (nullable int).
- **Single-Market Events vs Multi-Market Events**: Support standalone binary markets and multi-market categorical groupings where outcomes are mutually exclusive.

### 3.2 Outcome Tokens & Pricing Mechanics
- Each Market outcome is backed by a discrete **Outcome Token** (`token_id`, `condition_id`, `outcome_index`).
- Prices are strictly bounded between `$0.01` and `$0.99`, representing probability percentages (1% to 99%).
- Winning outcome tokens settle at exactly `$1.00` per share. Losing outcome tokens expire at `$0.00`. Total settlement payout across a complete outcome set strictly equals `$1.00`.
- Users can sell their position back to the order book prior to market settlement at current market prices to lock in profit or cut loss.

### 3.3 Negative Risk & Augmented Negative Risk
- For mutually exclusive multi-candidate events (e.g., "Who wins the nomination?"):
  - Holding `1 NO` of Market A is economically equivalent to holding `1 YES` of all other competing markets under that Event.
  - **Conversion Mechanism**: Atomic splitting and merging ($1 collateral = 1 share of every outcome; 1 share of every outcome merges back to $1 collateral).
  - **Augmented Negative Risk & Placeholders**: Dynamic introduction of new candidates/outcomes using placeholder tokens ("Other / Unannounced Candidate") without diluting or disrupting existing positions.

### 3.4 Parabolic Dynamic Trading Fee Model
Trading fees are calculated dynamically per matched fill using the category formula:
$$\text{Fee} = C \times \text{feeRate} \times p \times (1 - p)$$
Where:
- $C$ = Number of shares filled.
- $\text{feeRate}$ = Category-specific fee parameter (`Crypto`: 0.02, `Politics`: 0.015, `Sports`: 0.025, `Default`: 0.02).
- $p$ = Execution price of the outcome share ($0.01 \le p \le 0.99$).
- Fees are maximum at $p = 0.50$ (maximum uncertainty) and decay symmetrically towards 0 at $p \to 0$ and $p \to 1$.

### 3.5 Central Limit Order Book (CLOB) Matching Engine Logic
- **Price-Time Priority (FIFO)**: Resting limit orders are queued first-in, first-out at each discrete price level.
- **Maker vs Taker**: Existing resting orders in the book are Makers; incoming matching aggressive orders are Takers.
- **Supported Order Types**: Limit orders and Market orders (executed as marketable limit orders).
- **Time-in-Force (TIF)**:
  - `GTC` (Good 'Til Cancelled): Rests in the book until filled or explicitly cancelled.
  - `IOC` (Immediate or Cancel): Immediately fills as much as possible against resting liquidity; cancels any remaining unfilled balance immediately.
  - `FOK` (Fill or Kill): Requires the entire order amount to be filled immediately at the limit price or better; if liquidity is insufficient, rejects the entire order with 0 fills.
- **Execution Flags**:
  - `post_only`: Maker liquidity guarantee. If the order would immediately cross the spread and take liquidity, reject the order with **HTTP 409 Conflict** without generating fills.
- **Self-Trade Prevention (STP)**: If an incoming order would match against an existing resting order belonging to the same `user_id`, cancel the incoming aggressive order with status `REJECTED` to prevent wash trading.
- **Collateral Locking Invariant**:
  - Placing a `BUY` limit order locks $\text{price} \times \text{amount}$ available collateral in `CollateralAccount.locked_balance`.
  - Placing a `SELL` limit order locks $\text{amount}$ outcome shares from `Position.shares`.
  - Insufficient available balance must be rejected with **HTTP 400 Bad Request**.
- **Order State Machine**:
  - `PENDING` -> `OPEN` -> `PARTIALLY_FILLED` -> `FILLED` / `CANCELLED` / `EXPIRED` / `REJECTED`.
  - Orders can be cancelled **only while in the `OPEN` or `PARTIALLY_FILLED` state**. Cancellation attempts on orders in `FILLED`, `CANCELLED`, or `EXPIRED` state must be rejected with **HTTP 409 Conflict**.
- **Trade Execution States**:
  - `SUBMITTED` -> `MATCHED` -> `SETTLING` -> `CONFIRMED` / `FAILED`.

### 3.6 Market Resolution & Settlement Lifecycle
- **Resolution State Machine**:
  - `ACTIVE` -> `CLOSED` (trading halted; orders can no longer be placed) -> `IN_RESOLUTION` (oracle proposal with bonded stake) -> `DISPUTED` (challenge window active) -> `RESOLVED`.
- **Decentralized Oracle Integration**:
  - UMA Optimistic Oracle pattern: Proposer stakes a bond and asserts the winning outcome index.
  - A dispute window (e.g., 2 hours simulated / configurable) allows challengers to stake a counter-bond if the assertion is false.
  - Once finalized without dispute (or after dispute resolution), market transitions to `RESOLVED` and `winning_outcome_index` is locked.
- **Settlement & Redemption**:
  - Winning token holders redeem shares 1:1 for collateral ($1.00 USDC per winning share).
  - Losing token shares expire at $0.00.
  - Redemption is permitted **only when the market status is `RESOLVED`**, user holds `shares > 0`, and `claimed == False`. Once redeemed, mark `claimed = True` and credit `CollateralAccount.balance`.
  - Duplicate claim attempts on already claimed positions must be rejected with **HTTP 409 Conflict**.

---

## 4. DATABASE SCHEMAS & ENTITY RELATIONSHIPS

Define production SQLAlchemy ORM models with explicit column constraints, foreign keys, and indexes:

1. **User**: `id` (UUID PK), `email` (unique, indexed), `hashed_password` (string), `api_key` (unique, nullable), `created_at` (UTC timestamp).
2. **CollateralAccount**: `id` (UUID PK), `user_id` (UUID FK -> User.id, unique, indexed), `balance` (Numeric(18, 4), >= 0), `locked_balance` (Numeric(18, 4), >= 0), `currency` (VARCHAR(10), default 'USDC').
3. **Event**: `id` (UUID PK), `slug` (VARCHAR(100), unique, indexed), `title` (VARCHAR(255)), `description` (TEXT), `category` (VARCHAR(50), indexed), `tags` (JSON), `status` (VARCHAR(20), indexed), `start_date` (timestamp), `end_date` (timestamp), `total_volume` (Numeric(18, 4), default 0), `created_at` (timestamp).
4. **Market**: `id` (UUID PK), `event_id` (UUID FK -> Event.id, indexed), `condition_id` (VARCHAR(66), unique, indexed), `question` (VARCHAR(500)), `outcomes` (JSON), `tick_size` (Numeric(6, 4), default 0.01), `min_order_size` (Numeric(12, 4), default 5.0), `status` (VARCHAR(20), indexed), `neg_risk` (BOOLEAN, default False), `winning_outcome_index` (INTEGER, nullable), `created_at` (timestamp).
5. **OutcomeToken**: `id` (UUID PK), `token_id` (VARCHAR(100), unique, indexed), `market_id` (UUID FK -> Market.id, indexed), `outcome_index` (INTEGER), `symbol` (VARCHAR(20)).
6. **Order**: `id` (UUID PK), `user_id` (UUID FK -> User.id, indexed), `market_id` (UUID FK -> Market.id, indexed), `token_id` (VARCHAR(100) FK -> OutcomeToken.token_id, indexed), `side` (VARCHAR(10)), `type` (VARCHAR(10)), `price` (Numeric(6, 4)), `amount` (Numeric(18, 4)), `filled_amount` (Numeric(18, 4), default 0), `status` (VARCHAR(20), indexed), `time_in_force` (VARCHAR(10), default 'GTC'), `post_only` (BOOLEAN, default False), `created_at` (timestamp, indexed).
7. **TradeFill**: `id` (UUID PK), `market_id` (UUID FK -> Market.id, indexed), `token_id` (VARCHAR(100), indexed), `maker_order_id` (UUID FK -> Order.id), `taker_order_id` (UUID FK -> Order.id), `maker_user_id` (UUID FK -> User.id), `taker_user_id` (UUID FK -> User.id), `price` (Numeric(6, 4)), `shares` (Numeric(18, 4)), `maker_fee` (Numeric(18, 4)), `taker_fee` (Numeric(18, 4)), `timestamp` (timestamp, indexed).
8. **Position**: `id` (UUID PK), `user_id` (UUID FK -> User.id, indexed), `market_id` (UUID FK -> Market.id, indexed), `token_id` (VARCHAR(100), indexed), `shares` (Numeric(18, 4), default 0), `avg_entry_price` (Numeric(6, 4), default 0), `realized_pnl` (Numeric(18, 4), default 0), `is_settled` (BOOLEAN, default False), `claimed` (BOOLEAN, default False), `updated_at` (timestamp). Unique constraint on `(user_id, token_id)`.
9. **OracleDispute**: `id` (UUID PK), `market_id` (UUID FK -> Market.id, indexed), `proposed_outcome_index` (INTEGER), `proposer_address` (VARCHAR(100)), `bond_amount` (Numeric(18, 4)), `dispute_deadline` (timestamp), `status` (VARCHAR(20), default 'PROPOSED'), `created_at` (timestamp).

---

## 5. REST API SPECIFICATIONS WITH COMPLETE ENVELOPES

Implement standard REST endpoints matching the DexBuilder Prediction API with explicit status envelopes:

### 5.1 Public Endpoints
- `GET /api/v4/prediction/events`:
  - Query parameters: `status` (`ACTIVE`, `CLOSED`, `RESOLVED`), `category` (string), `sort_by` (`volume`, `liquidity`, `ending_soon`), `cursor` (string), `limit` (int, default 20, max 100).
  - Returns `200 OK` with `{ "events": [...], "next_cursor": str, "total_count": int }`.
- `GET /api/v4/prediction/events/{event_id}` & `/slug/{slug}`:
  - Returns `200 OK` with full Event details, aggregate volume, and array of child Markets.
  - Returns `404 Not Found` if event does not exist.
- `GET /api/v4/prediction/markets`:
  - Query parameters: `event_id`, `category`, `status`.
  - Returns `200 OK` with list of Markets, condition IDs, and outcome tokens.
- `GET /api/v4/prediction/markets/{market_id}`:
  - Returns `200 OK` with Market specification, tick size, min order size, and resolution details.
  - Returns `404 Not Found` if market does not exist.
- `GET /api/v4/prediction/tokens/{token_id}/order_book`:
  - Query parameters: `depth` (int, 1..100, default 50).
  - Returns `200 OK` with `{ "token_id": str, "bids": [[price, size], ...], "asks": [[price, size], ...], "timestamp": str }`.
  - Returns `404 Not Found` if token does not exist.
- `GET /api/v4/prediction/tokens/{token_id}/price` & `/ticker`:
  - Returns `200 OK` with `{ "last_price": Decimal, "bbo": { "best_bid": Decimal, "best_ask": Decimal }, "volume_24h": Decimal, "high_24h": Decimal, "low_24h": Decimal }`.
- `GET /api/v4/prediction/tokens/{token_id}/price_history`:
  - Query parameters: `resolution` (`1m`, `5m`, `1h`, `1d`), `from` (timestamp), `to` (timestamp).
  - Returns `200 OK` with OHLCV candlestick array: `[{ "timestamp": int, "open": float, "high": float, "low": float, "close": float, "volume": float }]`.

### 5.2 Private Authenticated Endpoints
- `POST /api/v4/prediction/orders`:
  - Headers: `Authorization: Bearer <token>` or HMAC signature.
  - Request Body:
    ```json
    {
      "market_id": "UUID",
      "token_id": "string",
      "side": "BUY" | "SELL",
      "type": "LIMIT" | "MARKET",
      "price": 0.55,
      "amount": 25.0,
      "time_in_force": "GTC",
      "post_only": false
    }
    ```
  - Validation: Validates price in `[0.01, 0.99]`, amount >= `min_order_size`, price is multiple of `tick_size`, user has sufficient collateral (for BUY) or token shares (for SELL).
  - Response:
    - Returns `201 Created` with created order object and any immediate execution fills.
    - Returns `400 Bad Request` if insufficient collateral, invalid price bounds, or amount < min_order_size.
    - Returns `401 Unauthorized` if token is missing or invalid.
    - Returns `409 Conflict` if market is closed, or post-only order crosses spread.
    - Returns `422 Unprocessable Entity` on malformed schema.
- `GET /api/v4/prediction/orders`:
  - Query parameters: `market_id`, `status` (`OPEN`, `FILLED`, `CANCELLED`), `limit` (default 50).
  - Returns `200 OK` with list of authenticated user's orders only. Returns `401 Unauthorized` if unauthenticated.
- `DELETE /api/v4/prediction/orders/{order_id}`:
  - Cancels specific open order.
  - State Guard: Order must belong to the calling user and be in `OPEN` or `PARTIALLY_FILLED` state.
  - Returns `200 OK` with `{ "order_id": str, "status": "CANCELLED", "unfilled_amount": Decimal }`.
  - Returns `401 Unauthorized` if unauthenticated.
  - Returns `403 Forbidden` if order belongs to a different user.
  - Returns `404 Not Found` if order does not exist.
  - Returns `409 Conflict` if order is already `FILLED`, `CANCELLED`, or `EXPIRED`.
- `DELETE /api/v4/prediction/orders`:
  - Batch cancel by `market_id` or `condition_id`. Cancels all active orders for the authenticated user in that market.
  - Returns `200 OK` with `{ "cancelled_count": int, "cancelled_order_ids": [...] }`.
- `GET /api/v4/prediction/positions`:
  - Query parameters: `settlement_status` (`OPEN` | `SETTLED`).
  - Returns `200 OK` with authenticated user positions: `{ "positions": [{ "position_id": str, "market_id": str, "token_id": str, "shares": float, "avg_entry_price": float, "current_price": float, "unrealized_pnl": float, "is_settled": bool, "claimed": bool }] }`.
- `POST /api/v4/prediction/positions/{position_id}/redeem`:
  - Redeems winning outcome tokens for $1.00 collateral payout per share.
  - State Guard: Position must belong to the caller, associated market must have status `RESOLVED`, position must have `shares > 0`, and `claimed == False`.
  - Returns `200 OK` with `{ "position_id": str, "payout_amount": Decimal, "status": "SETTLED_CLAIMED" }`.
  - Returns `401 Unauthorized` if unauthenticated.
  - Returns `403 Forbidden` if position belongs to a different user.
  - Returns `404 Not Found` if position does not exist.
  - Returns `409 Conflict` if market is not in `RESOLVED` status, or position was already claimed.
- `POST /api/v4/prediction/resolution/propose`:
  - Market Admin / Proposer asserts winning outcome index and stakes bond.
  - Returns `200 OK` or `409 Conflict` if market is not `CLOSED`.
- `POST /api/v4/prediction/resolution/dispute`:
  - Challenger posts counter-bond during active dispute challenge window.
  - Returns `200 OK` or `409 Conflict` if dispute window has expired.

---

## 6. REAL-TIME WEBSOCKET ARCHITECTURE & SCHEMAS

Implement a robust WebSocket server and typed client connection layer:

### 6.1 Public Channels (`ws://<host>/api/v4/prediction/ws/public`)
- Subscription protocol: Send `{ "action": "subscribe", "channel": "pred.depth", "token_id": "string" }`.
- `pred.bbo`: Publishes `{ "channel": "pred.bbo", "token_id": str, "best_bid": float, "best_ask": float, "last_price": float, "timestamp": int }`.
- `pred.depth`: Publishes full initial snapshot upon connect, followed by incremental delta updates `[price, new_size]`.
- `pred.trades`: Live trade execution feed `{ "channel": "pred.trades", "market_id": str, "token_id": str, "price": float, "shares": float, "side": "BUY"|"SELL", "timestamp": int }`.
- `pred.status`: Broadcasts market state transitions (`ACTIVE` -> `CLOSED` -> `IN_RESOLUTION` -> `RESOLVED`) and official winning outcome index.
- `pred.candlestick`: Real-time OHLCV bar updates for active interval (`1m`, `5m`, `1h`, `1d`).

### 6.2 Private Authenticated Channels (`ws://<host>/api/v4/prediction/ws/private`)
- Handshake: Authenticate connection via `?token=<JWT>` or `{ "action": "auth", "token": "string" }`. Rejection with close code `4401` on invalid auth.
- `pred.orders`: Pushes immediate order state changes: `{ "order_id": str, "status": "PARTIALLY_FILLED", "filled_amount": float, "remaining_amount": float }`.
- `pred.usertrades`: Private fill notifications: `{ "fill_id": str, "order_id": str, "price": float, "shares": float, "fee_paid": float, "role": "maker"|"taker" }`.
- `pred.positions`: Real-time updates to user share balances, average entry price, and unrealized PnL.
- `pred.settlements`: Real-time notification when held market resolves and payout claim is ready.

---

## 7. USER INTERFACE SPECIFICATIONS & FRONTEND OPERATIONAL RULES

Build a responsive, modern web application (Tailwind CSS v4, Lucide icons, glassmorphism UI cards, dark/light theme) containing 4 dedicated views:

### Page 1: Market Discovery & Explore (`/` and `/markets`)
- **Hero & Tickers**: Platform 24h aggregate volume, total open interest, trending banner.
- **Search & Filters**:
  - Full-text search for event titles, descriptions, and tag keywords.
  - Category selector: Politics, Crypto, Sports, Macro, Pop Culture, Tech.
  - Status filter tabs: `All`, `Active`, `Ending Soon`, `Resolved`.
  - Sorting: Highest Volume, Highest Liquidity, Newest, Ending Soonest.
- **Event Card Grid**:
  - Event title, category badge, 24h volume, expiry countdown timer.
  - Multi-market preview: Candidate/outcome rows with live probability bars (% YES / % NO) and instant "Buy" triggers opening the trade drawer.

### Page 2: Event & Market Detail (`/event/:slug` or `/market/:id`)
- **Header Section**:
  - Event title, active status badge (`Active`, `Closed`, `Resolving`, `Resolved`), end date, total volume, liquidity depth.
  - UMA Oracle resolution criteria and verifiable data source accordion.
- **Sub-Market Switcher (for Multi-Market Categorical Events)**:
  - Tabbed or list selector for individual candidates/outcomes.
  - Negative Risk indicator & parity price monitor ($\sum P_i \approx 1.00$).
- **Interactive Price Chart**:
  - Timeframe toggles: `1H`, `1D`, `1W`, `1M`, `ALL`.
  - Candlestick (OHLCV) and smooth line probability charts.
- **Live Order Book & Depth Ladder Widget**:
  - Bid / Ask ladder with price, size, cumulative depth bars, and spread visualization.
  - Tick size selector (`0.01`, `0.05`, `0.1`).
- **Recent Trades Feed**: Live matched trades stream with timestamp, side, price, and share size.
- **Sticky Order Entry Drawer / Modal**:
  - Action toggle: `Buy` vs `Sell`.
  - Outcome selector: `Yes` vs `No` (or candidate buttons).
  - Order type toggle: `Market` vs `Limit`.
  - Inputs: Share Price ($0.01 - $0.99 for limit), Share Amount / Total Collateral ($).
  - Advanced controls: TIF selector (`GTC`, `IOC`, `FOK`), `Post-Only` checkbox.
  - Dynamic fee preview calculating $C \times \text{feeRate} \times p \times (1 - p)$.
  - Return calculator: Average execution price, Max Profit ($), Potential Return (%).
  - Pre-order validation warnings: insufficient balance, minimum order size violation, price outside $[0.01, 0.99]$.

### Page 3: User Portfolio & Activity Center (`/portfolio`)
- **Financial Summary Cards**:
  - Total Portfolio Value ($).
  - Available Collateral Balance (USDC).
  - Locked Collateral in open limit orders ($).
  - Unrealized PnL ($ and %) & Realized PnL ($).
- **Tabs Section**:
  1. **Active Positions**: Columns: Event/Market, Outcome Token, Shares Owned, Avg Entry Price, Current Price, Current Value, Unrealized PnL ($ / %), Action (`Sell / Close Position`).
  2. **Settled Positions & Redemption**: Displays resolved markets where user holds outcome tokens. Distinct **"Claim Payout"** CTA button for winning shares (paying out $1.00 per share) with instant settlement receipt.
  3. **Open Orders Management**: Columns: Timestamp, Market, Outcome, Side, Price, Original Size, Filled %, Status. Actions: Single-order `Cancel` button; top-level `Cancel All` and `Cancel All in Market` buttons.
  4. **Trade Execution History**: Historical filled trades with trade ID, fill price, shares, taker/maker fee paid, and timestamp.
  5. **Cash Ledger / Deposits & Withdrawals**: Collateral deposit/withdrawal simulation modal and ledger table.

### Page 4: Resolution & Oracle Dispute Portal (`/resolution`)
- Public view of all markets in `IN_RESOLUTION` or `DISPUTED` status.
- Proposed winning outcome, oracle proposer address, dispute expiration countdown timer.
- Dispute action interface (stake bond to challenge incorrect resolution).
- History of finalized settlements with transaction hashes.

---

## 8. FAILURE & NEGATIVE EDGE CASES (ERROR MATRIX)

The system must explicitly handle, reject, and test the following failure scenarios:
- **HTTP 400 Bad Request**:
  - Order price $< 0.01$ or $> 0.99$.
  - Order size $<$ `min_order_size` (e.g. 5.0 shares).
  - Price is not a valid discrete multiple of `tick_size`.
  - Insufficient available collateral for BUY order or insufficient token shares for SELL order.
  - Negative collateral deposit or withdrawal amount.
- **HTTP 401 Unauthorized**:
  - Missing, invalid, or expired JWT bearer token.
  - Invalid HMAC signature on private REST endpoints or WebSocket auth handshake.
- **HTTP 403 Forbidden**:
  - Authenticated user attempting to view, cancel, or modify another user's order.
  - Authenticated user attempting to redeem another user's position.
- **HTTP 404 Not Found**:
  - Nonexistent `event_id`, `slug`, `market_id`, `token_id`, `order_id`, or `position_id`.
- **HTTP 409 Conflict**:
  - Order cancellation request on an order that is already in `FILLED`, `CANCELLED`, or `EXPIRED` status.
  - Placing a `post_only` order that would immediately cross the opposite side of the order book spread.
  - Submitting new orders to a market that is `CLOSED`, `IN_RESOLUTION`, or `RESOLVED`.
  - Redeeming outcome tokens for a market that has not reached `RESOLVED` status.
  - Redeeming an already claimed position (`claimed == True`).
  - Challenging an oracle proposal after the dispute expiration window has closed.
- **HTTP 422 Unprocessable Entity**:
  - Malformed JSON payloads, missing required fields, or invalid enum parameters (`side != BUY|SELL`, invalid TIF).

---

## 9. AUTOMATED VERIFICATION & CONCRETE TEST SUITE REQUIREMENTS

Provide comprehensive automated test suites using `pytest` and `pytest-asyncio`:

### 9.1 Unit Tests (`tests/test_clob_engine.py`)
- **Price-Time Priority**: Assert that two limit orders at the same price are matched FIFO.
- **Spread & Crossing**: Assert maker/taker price assignment (resting order price forms execution price).
- **Execution Flags**:
  - Assert `post_only` order crosses the spread and is rejected with HTTP 409 without resting in the book.
  - Assert `IOC` fills partial liquidity and immediately cancels remaining size.
  - Assert `FOK` cancels completely with 0 fills if requested size cannot be filled immediately.
- **Self-Trade Prevention**: Assert incoming order matching existing order from same user is rejected.
- **Dynamic Parabolic Fee Formula**:
  - Assert that fee equals $C \times \text{feeRate} \times p \times (1 - p)$.
  - Assert that fee is strictly highest at $p = 0.50$ and symmetric at $p = 0.10$ and $p = 0.90$.
- **Conditional Token Math**: Assert atomic collateral splitting ($1.00 \to 1 \text{ YES} + 1 \text{ NO}$) and merging ($1 \text{ YES} + 1 \text{ NO} \to \$1.00$).

### 9.2 Integration Tests (`tests/test_api_endpoints.py`)
- Use `httpx.AsyncClient` against the FastAPI application.
- **Discovery**: Test event/market listing, category filtering, search, and cursor pagination.
- **Order Placement & Fills**: Place matching BUY and SELL orders, assert trade fill generation, position creation, and collateral balance deduction.
- **Multi-User Isolation**: User A creates an order; User B attempts to cancel User A's order; assert **HTTP 403 Forbidden** (or **404**).
- **Order State Guards**: Attempt to cancel an order after it has been fully filled; assert **HTTP 409 Conflict**.
- **Negative Error Matrix**: Assert 400, 401, 403, 404, 409, and 422 responses on all invalid input scenarios.
- **Settlement & Redemption**:
  - Resolve market with outcome index 0.
  - Holder of winning token redeems shares; assert payout of $1.00 per share credited to collateral account.
  - Holder of losing token redeems shares; assert $0.00 payout.
  - Attempt duplicate redemption on claimed position; assert **HTTP 409 Conflict**.

### 9.3 WebSocket Streaming Tests (`tests/test_websocket_stream.py`)
- Test public BBO and depth ladder broadcasts when new limit orders are placed and matched.
- Test authenticated private channel subscription receiving real-time order fill updates.

---

## 10. OBSERVABLE COMPLETION CRITERIA & DEFINITION OF DONE

The implementation is complete when:
1. **Clean Environment Startup**: The FastAPI backend starts cleanly in a fresh environment without hanging daemon processes.
2. **Schema & Migration Pass**: Database tables and indexes initialize without errors.
3. **Automated Test Suite Pass**: All automated pytest unit, integration, and WebSocket tests pass with zero failures (`exit code 0`).
4. **Static Frontend Compilation**: Frontend static bundle compiles cleanly via `npm run build` with zero TypeScript errors.
5. **Githeri Contract Verification Gate**: Full contract verification (`githeri verify` or `pytest`) passes with exit code 0.
