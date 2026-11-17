# Dolymarket Engineering Sprints & Roadmap (Single Source of Truth)

> **Single Source of Truth** consolidating all active, completed, and planned work from [dexbuilder-todo.md](dexbuilder-todo.md), [security-audit.md](security-audit.md), [improve.md](improve.md), and [GRG_APPLICATION.md](GRG_APPLICATION.md).

**Legend:** `[x]` Done · `[ ]` Open · `[~]` Blocked on upstream / external dependency

---

## Sprint 1 — Core Platform, Live DexBuilder Reads & Admin Console (Completed)

- [x] **CLOB & Settlement Core**: Price-time-priority matching engine (`app/engine/clob.py`), batched write-behind fill queue (`app/engine/fill_queue.py`), conditional-token settlement (`app/services/settlement.py`), collateral ledger (`app/services/collateral.py`).
- [x] **Live Public DexBuilder Data**: Markets (`active` + `closed`/`resolved` pagination), market detail, events, order books, price history (candlestick fallback), candlesticks, trade tape, tags, server time (`app/api/v4/prediction/live.py`, `app/services/live_data.py`).
- [x] **Frontend Live & Discovery Views**: `LiveMarketsPage.tsx`, `LiveMarketDetailPage.tsx`, `MarketDetailPage.tsx`, `TagsPage.tsx`, `UserTradesPage.tsx`, `SettledPositionsPage.tsx`, `EventDetailPage.tsx`.
- [x] **Pro Desks & Copy Trading**: Desk creation (standard + 500 AGX-bonded Pro Desks), track records, follower limits, drawdown breakers, and exactly-once fill mirroring (`app/api/v1/desks.py`, `app/services/copy_engine.py`, `CopyActivityPage.tsx`).
- [x] **Admin Console**: Event/market creation & closing, Pro Desk review, copy-job audit, AGX reconciliation (`app/api/v4/admin.py`, `AdminPage.tsx`).
- [x] **WebSocket Bridge**: Server-side DexBuilder WS protocol adapter (`app/ws/dexbuilder_stream.py`, `app/api/v4/ws_live.py`) with REST polling fallback.

---

## Sprint 2 — Security Audit & Contract Hardening (Completed + Remaining)

### Completed (`2026-11-12`)
- [x] **C-1 / C-2**: Gate `resolution/propose|dispute|finalize` behind `require_admin`; remove `"CLOSED"` bypass from `finalize_resolution`.
- [x] **C-3**: Gate private DexBuilder proxy routes behind `get_current_user` + `X-User-Wallet-Address` (`app/api/v4/dexbuilder/proxy.py`).
- [x] **C-4**: Bounded `Decimal` `AmountRequest` (100k cap, finite check) + per-credential rate limits on deposit/withdraw.
- [x] **C-5**: Fail fast on missing or known-default `JWT_SECRET` in `app/core/security.py`.
- [x] **C-6**: Fix admin `sync-balance` to credit the target `user_id`.
- [x] **H-1 / H-2**: WebSocket origin allowlist, live-account re-check, duplicate-accept fix; register/passkey auth rate limiting + `TRUST_PROXY_HEADERS`.
- [x] **H-3 / H-4 / H-5**: `Decimal` validation on money fields; HTTP errors on engine rejections (409 self-trade); savepoint + logging on copy-trade mirroring.
- [x] **H-6 / H-7 / H-8 / H-9**: Drop legacy token key, clear expired tokens, scope Cancel-All per market, fix `sort_by=volume` & `ending_soon`, expose `is_admin` on OAuth/passkey responses.

### Remaining Security & Contract Backlog
- [ ] **Cookie Session + CSRF (H-6, M-6)**: Move JWT from `localStorage` to `HttpOnly; Secure; SameSite=Lax` cookies with CSRF double-submit; narrow default `CORS_ALLOW_ORIGINS`.
- [ ] **Authz Matrix Suite**: Parametrized regression suite hitting every mutating route as `(anonymous, non-admin, admin)` asserting `401`/`403`.
- [ ] **OpenAPI Type Generation (M-1)**: Add strict Pydantic response models across all routes and generate frontend types via `openapi-typescript` to eliminate `any`.
- [ ] **SQL & N+1 Optimization (M-2)**: Single-aggregate desk track records, windowed bulk prices, SQL volume aggregates, UTC-aware datetime consistency (`M-4`, `M-11`).
- [ ] **Observability & Audit Trail (P3)**: Structured request-ID logging, alerts on rejected-order spikes / mirror failures, persistent admin/oracle action audit table.
- [ ] **Input Bounds & Rate Limits (P3)**: `max_length` caps on string IDs/slugs; per-IP + per-token rate limits on live/prediction read routes.

---

## Sprint 3 — Broker Auth, Turso DB, Order Routing & Live Fear & Greed Hero (Completed)

- [x] **HMAC-SHA512 Broker Auth Verified**: Fixed `check_credentials()` in `app/services/dexbuilder.py` to probe `/api/v4/dexbuilder/assets`; added `DEXBUILDER_BROKER_ID`; verified `200 OK` on Broker reads (`/api/v4/broker/prediction/orders|positions|usertrades|account_book|claims/available`, `/api/v4/dexbuilder/user/info|deposit/history|withdraw/history`) for bound wallet.
- [x] **Broker Order Proxy & Live Trade Ticket**: Added `place_order()`, `get_order()`, `cancel_order()`, `cancel_orders_by_condition()` in `app/services/dexbuilder.py` and `app/api/v4/dexbuilder/proxy.py`; built `frontend/src/components/LiveTradeTicket.tsx` and wired open-order cancellation in `LiveMarketDetailPage.tsx`.
- [x] **Broker Account Portfolio Panel**: Added `account_book`, `claims/available`, `claims`, and platform `deposits`/`withdrawals` endpoints + `frontend/src/components/DexBuilderBrokerPanel.tsx` (`Broker Account` tab in `PortfolioPage.tsx`).
- [x] **Turso libSQL & Alembic Migrations**: Added `alembic` async/libSQL setup (`alembic/env.py`, `alembic/versions/89024bdc0b25_initial_schema.py`), Turso runtime adapter (`_LibsqlAsyncSession`) in `app/db/session.py`, and migrated 29 tables to Turso (`alembic check` clean).
- [x] **Health Endpoint**: Added `GET /health` alongside `GET /api/health` in `app/main.py`.
- [x] **Web3 SIWE & Gate Wallet Discovery**: Fixed dynamic SIWE `domain`/`URI` binding from request origin (`app/api/v1/auth.py`), `eth_chainId` sync on mount/connect/switch, and EIP-6963 + `window.gatewallet` discovery (`WalletContext.tsx`, `WalletConnectModal.tsx`).
- [x] **Live Gate.io Fear & Greed Hero**: Built `app/services/fear_greed.py` + `app/api/v1/feargreed.py` streaming Gate.io `BTC_USDT` futures (`futures.trades` + `futures.order_book` + `10s` candles) with default `microstructure` profile and `0.25s` WS broadcast to `frontend/src/components/HeroVisual.tsx`.
- [x] **Env Hygiene**: Set `JWT_SECRET`, `DATABASE_URL`, `DATABASE_TOKEN` in `.env` (gitignored); aligned `.env.example` with HS256 / 24h TTL.

---

## Sprint 4 (NEXT) — Fear & Greed Market-Making Pro Desk Strategy

**Goal:** Run our own **Market-Making Pro Desk** that quotes two-sided `post_only` liquidity using live signals from `fear_greed_service` (`microstructure` profile, `10s` candles, `0.25s` WS ticks), with follower fill-mirroring via `copy_engine`.

### 4.1 Desk & Copy-Trading Integration
- [ ] **Dedicated MM Desk**: Provision a Pro Desk owned by the house/operator account (`app/api/v1/desks.py`).
- [ ] **Fill-Only Mirroring Guard**: Verify `copy_engine` mirrors only executed `TradeFill` rows (`source_fill_id`) and never churns followers on resting quote cancel/replace cycles, respecting `DESK_STALENESS_BPS` (`200`) and `DESK_DRAWDOWN_BREAKER_PCT` (`20%`).

### 4.2 Quoting Engine (`app/services/market_maker.py`)
- [x] **Signal Inputs**: Consume `BTCFearGreedReading` from `app/services/fear_greed.py` (`score_0_100`, `v_alpha`, `m_alpha`, `ewi`, `regime_state`, `dvol`, `bid_ask_imbalance`, `early_warning`).
- [x] **Fair Value & Sentiment/Velocity Skew**:
  - Crypto/BTC markets: `fair = book_mid + k_fg * ((score_0_100 - 50) / 50) + k_vel * v_alpha` (clamped to `[0.02, 0.98]`).
  - Non-crypto markets: `fair = book_mid` (use `ewi`/`dvol` strictly for spread widening & toxicity halts).
- [x] **Inventory Skew (Binary `$0–$1` Cap)**:
  - Track net YES/NO inventory `q` vs `max_inventory`.
  - Shift fair value by `-gamma * (q / max_inventory)` to mean-revert inventory toward flat.
- [x] **EWI Regime-Gated Spread & Toxicity Kill-Switch** (per [GRG_APPLICATION.md](GRG_APPLICATION.md)):
  - `STABLE` (`ewi < 0.45`): tight half-spread (`1–2¢`), full `quote_size`.
  - `ELEVATED` (`0.45 <= ewi < 0.75`): widen half-spread `2x–3x`, reduce `quote_size` by `50%`.
  - `CRITICAL` (`ewi >= 0.75` or `early_warning == True`): **cancel all resting quotes immediately** and pause new quoting until `ewi < 0.55` hysteresis clears.
- [x] **Requote Loop (`post_only=True`)**:
  - Poll/react on `1s–2s` cadence; cancel/replace only when `|target_px - resting_px| >= tick_size` to stay within rate limits (`ORDER_RATE`).
  - Support `dry_run=True` (paper-quoting + simulated fills/PnL) before enabling live order submission.

### 4.3 Execution Targets (Phase A -> Phase B)
- [x] **Phase A (Local CLOB — Unblocked Today)**: Submit/cancel `post_only` LIMIT orders via `MatchingEngine` (`desk_id` tagged) on active local markets.
- [ ] **Phase B (Live DexBuilder — After `event_contracts` Key Approval)**: Swap order sink to `DexBuilderClient.place_order` / `cancel_order` on live 5m `BTC Up or Down` (`ge_*`) markets.

### 4.4 API, UI & Calibration
- [x] **Desk MM Control API**: Added `POST /api/v1/desks/{desk_id}/mm/start`, `POST /api/v1/desks/{desk_id}/mm/stop`, `GET /api/v1/desks/{desk_id}/mm/status` (desk-owner / admin gated).
- [x] **UI Telemetry**: Built `frontend/src/components/DeskMarketMakerPanel.tsx` and mounted on `DeskDetailPage.tsx` (start/stop, dry-run/crypto-skew toggles, live Regime/EWI, F&G score, Fair Value, Bid/Ask quotes, ticks & order counts).
- [x] **Backtest Calibration**: Built `scripts/calibrate_mm.py` against Gate.io `10s` (500 bars) & `1m` (600 bars) BTC_USDT candles; confirmed `k_fg=0.04–0.06`, `k_vel=0.25`, `gamma=0.02–0.05` and highlighted that two-way noise flow + `post_only` spread capture is required (pure informed-flow fills lose money).
- [x] **Tests**: Unit + integration tests (`tests/test_market_maker.py`) for inventory skew, `ewi >= 0.75` quote pull, hysteresis, `crypto_skew`, and MM control API authz.

### 4.5 Multi-Market GRG MM Hardening (ALGOXEN Alignment — Step 1)
- [x] **Multi-market per Desk**: Changed `desk_mm_configs` PK from `desk_id` -> `(desk_id, token_id)` so one Desk quotes multiple Official markets concurrently.
- [x] **Capital & Loss Caps**: Per-market `max_usdc_exposure` + `daily_loss_limit_usdc` circuit breaker.
- [x] **Pre-Expiry & Local Toxicity Guard**: Pulls quotes `N` minutes before `Event.end_date` and halts on sudden local book midpoint jumps (`>= 8¢/tick`).
- [x] **Auto-Resume**: Persists and resumes all `(desk_id, token_id)` bots on boot.

---

## Sprint 5 — Community Markets, Hybrid LMSR AMM & Upstream Cutover

### Official vs Community Markets (ALGOXEN Alignment — Step 2)
- [x] **Market Tiers & Status**: Added `tier` (`OFFICIAL` | `COMMUNITY`), `creator_user_id`, `resolution_criteria`, `liquidity_funded_usdc`, and `UNFUNDED` status to `Event`/`Market`.
- [x] **Creator Market Flow**: Extracted shared market builder (`app/services/markets.py`) -> `POST /api/v4/prediction/community/markets` & `POST /api/v4/prediction/community/markets/{id}/fund` with prohibited-category safeguards + resolution criteria + funding threshold (`$10` USDC).
- [x] **UI Badges**: Added `Community` and `Unfunded` badges on `MarketsPage.tsx`.

### Hybrid LMSR AMM Pool (ALGOXEN Alignment — Step 3)
- [x] **AMM Pool Engine**: Added `AmmPool` & `AmmLpPosition` (`app/services/amm.py`, `app/api/v4/amm.py`) with overflow-safe LMSR pricing, instant BUY/SELL execution, fee collection, and post-resolution LP redemption; community market funding automatically seeds `AmmPool`.
- [x] **Tests**: `tests/test_amm.py` & `tests/test_community_markets.py` covering LMSR math, funding activation, AMM trades, and fee accrual.

### Upstream DexBuilder Dependencies
- [~] **Event Contracts Permission**: Waiting on DexBuilder product team to enable `event_contracts` (`read + write`) on Broker API key; then verify live `ge_*` order placement + cancel end-to-end and purge local seeded markets.
- [~] **Live WebSocket Broker**: Re-verify `wss://broker.dexbuilder.com/ws/dex-builder/prediction` once upstream resolves `HTTP 503` (local bridge tested against fake broker).

### Product & Deployment
- [x] **On-Chain USDC Deposit/Withdraw Signing**: Wired `WalletContext.tsx` (`viem` ERC-20 `balanceOf` on-chain USDC balance, `eth_signTypedData_v4`, `eth_sendTransaction`), `DexBuilderTransferModal.tsx`, `DexBuilderBrokerPanel.tsx`, `WalletButton.tsx`, and `CashLedgerModal.tsx` to `/api/v4/dexbuilder/platform/deposit/sign_data`, `/withdraw/sign_data`, and `/withdraw/submit`.
- [x] **Hero Image Asset**: Closed — current hero backdrop accepted as final.
- [x] **OAuth & WebAuthn Deployment Parity**: Closed — federated OAuth (`GOOGLE_*` / `MICROSOFT_*` / `APPLE_*`) not needed; non-custodial SIWE + Passkeys + Email active (add prod domains to `WEBAUTHN_ORIGINS` on deploy).
- [x] **CI Postgres Parity**: Added `.github/workflows/ci.yml` (`backend-sqlite`, `backend-postgres` with `postgres:16-alpine` + `asyncpg` + `alembic upgrade head`, and `frontend-build`) and added `use_alter=True` on `Order.copy_source_fill_id` so Postgres schema teardown works cleanly.

---

## Pre-Sprint 6 — Closeable Code-Review Gaps

- [x] **Gap 1 — Turso `record_fee` Silent Skip (`app/engine/clob.py`)**: Guarded `session.begin_nested()` with `hasattr(session, "begin_nested")` so SQLite/Postgres use a savepoint and Turso `_LibsqlAsyncSession` (where Hrana rejects `SAVEPOINT`) calls `agx_service.record_fee(...)` directly.
- [x] **Gap 2 — AMM Fee Accrual to AGX Epoch (`app/services/amm.py`)**: Split 1% AMM fee 50/50 between `AmmPool.fees_collected_usdc` (LPs) and `agx.record_fee(...)` (staker/creator epoch); verified in `tests/test_amm.py`.
- [x] **Gap 3 — `ensure_market_bond` Opt-In (`app/api/v4/community.py`)**: Added optional `bond_with_agx: bool = False` on `CreateCommunityMarketRequest` calling `agx.ensure_market_bond(...)` while keeping zero-AGX community markets working via `$10` USDC funding.
- [x] **Gap 4 — Collateral Demo Faucet Prod Guard (`app/api/v1/collateral.py`)**: Gated `POST /api/v1/collateral/deposit` behind `ENABLE_DEMO_COLLATERAL` (auto-disabled when `APP_ENV=production`) + `Idempotency-Key` header deduplication.
- [x] **Gap 5 — Desk Portfolio-Wide Exposure Cap (`app/services/market_maker.py`)**: Added `desk_max_total_exposure_usdc` (`$2,000` default) across all `DeskPosition` rows for `cfg.desk_id` (`DESK_TOTAL_EXPOSURE_CAP` halt).
- [x] **Gap 6 — Automated AGX 24h Epoch Rollover (`app/services/agx.py` / `app/main.py`)**: Added `agx.distribute_matured_epochs()` + lifespan background rollover task (every 15m, cleanly cancelled on shutdown).
- [x] **Gap 7 — `GET /api/v1/desks/mine` 404 Toast Noise (`frontend/src/api/client.ts` / `DesksPage.tsx`)**: Added `silent` flag to `ApiClient.request` & `getMyDesk(true)` so initial Desk probe for users without a Desk suppresses error toast.

---

## Sprint 6 — Next-Gen Execution, Oracle Clarity & Pro UX (Beyond Kalshi & Polymarket)

### 6.1 Atomic CLOB + AMM Smart Order Router (Guaranteed Exit Liquidity)
- [x] **Unified Quote & Sweep Engine**: Added `POST /api/v4/prediction/orders/smart-quote` and `POST /api/v4/prediction/orders/smart` (`app/services/router.py`, `app/api/v4/orders.py`) comparing CLOB depth against LMSR `AmmPool` marginal price and executing atomically across both venues.
- [x] **MM-Halt Fallback**: Verified in `tests/test_smart_router.py` that when CLOB depth is empty, urgent exits route 100% to `AmmPool`.
- [x] **UI Execution Preview**: Added `Smart Route` mode in `TradeTicket.tsx` showing live CLOB vs AMM split, blended avg price, and `AMM Backstop Active` badge.

### 6.2 Oracle Clarity Score & Deterministic Resolution Feeds
- [x] **Pre-Trade Clarity Score**: Added `compute_clarity_score()` (`app/services/oracle.py`), exposed `clarity` & `oracle_feed` on market payloads (`public.py`, `community.py`), and rendered `Oracle Clarity` badge on `MarketDetailPage.tsx`.
- [x] **Deterministic Price/Event Feeds**: Added `POST /api/v4/prediction/resolution/resolve-feed` (`static`, `gate`, `coingecko` feeds) storing structured proof JSON on `OracleDispute.evidence_json` (with Alembic migration `887147b0e5f3`).
- [x] **Transparent Dispute Evidence**: Attached `evidence` on `ProposeRequest` / `DisputeRequest` and rendered `Oracle Proof / Evidence` on `ResolutionPage.tsx`.

### 6.3 Live Microstructure "Market Health & Toxicity" Shield
- [x] **Retail Toxicity Warning**: Exposed `fear_greed_service` `EWI`, regime (`STABLE`/`ELEVATED`/`CRITICAL`), and live spread in `TradeTicket.tsx` with explicit Limit/Smart Route warning on wide/toxic books.
- [x] **Spread & Depth Telemetry**: Added live bid-ask spread (¢), `$100` buy-impact slippage (bps), and EWI Toxicity Shield cards on `MarketDetailPage.tsx`.

### 6.4 Pro Order Controls & Cost-Basis P&L Parity
- [x] **One-Tap Position Flip & TP/SL**: Added `TP +20%` (resting GTC limit sell) and `Reverse` (atomic close + opposite outcome flip via `placeSmartOrder`) on open positions in `PortfolioPage.tsx`.
- [x] **Explicit TIF & Exact P&L**: Added explicit `GTC` / `IOC` / `FOK` execution descriptions in `TradeTicket.tsx` and `Cost Basis` + exact unrealized P&L (`$ / %`) in `PortfolioPage.tsx`.

### 6.5 Non-Custodial Withdrawal Transparency
- [x] **On-Chain Tx Links & Status**: Surfaced Basescan/Etherscan/Arbiscan/Optimism/Polygonscan explorer links, `nonce`, and status pills on deposits & withdrawals in `DexBuilderBrokerPanel.tsx`.

---

## Audit Hardening (Batches 1–3 from `GPT_AUDIT.md`)
- [x] **Batch 1 — CLOB & Auth Safety**: Per-token `asyncio.Lock` + maker `with_for_update()`, multi-level STP loop guard, non-truncating fee check, wallet auth routes added to `AUTH_ATTACK_PATHS`, rollover exception logging, and HMAC mutation replay cache.
- [x] **Batch 2 — Post-Commit WS, Prod DB & SIWE**: Post-commit WS broadcast queue (`queue_post_commit`), fail-fast `APP_ENV=production` SQLite/auto-DDL guard, canonical SIWE domain/URI, and atomic `DELETE` challenge consumption.
- [x] **Batch 3 — Frontend Perf & Accessibility**: `React.lazy` + `Suspense` route splitting (`index.js` `467 kB -> 110.9 kB`), `role="dialog"` / `aria-modal` / `Escape` / labeled inputs across all modals.

---

## Sprint 7 — Production Scale, Distributed Matching & Hardening

### 7.1 Authoritative Distributed Matching & Transactional Outbox
- [ ] **Partitioned Matching Leader & Durable Sequences**: Route each `token_id` to an authoritative matching partition with persisted per-partition sequences and deterministic restart/replay recovery.
- [ ] **Transactional Outbox & Broker Fan-Out**: Persist committed order/fill/depth events to an outbox table in the same DB transaction and relay to Redis Streams / Kafka for multi-pod WebSocket fan-out.
- [ ] **Postgres Concurrency & Deadlock Suite**: Add multi-task PostgreSQL stress tests for overfill, oversell, cancel-vs-fill, and deterministic account/position lock ordering.

### 7.2 Auth, Session & WebSocket Hardening
- [ ] **Short-Lived Access + HttpOnly Refresh Cookies**: Move browser sessions from 24h `localStorage` bearer tokens to short-lived in-memory access tokens + rotating/revocable `HttpOnly`/`Secure`/`SameSite` refresh cookies with CSRF protection.
- [ ] **Single-Use WebSocket Tickets & Backpressure**: Replace query-param JWTs on `/ws` with single-use short-lived tickets; enforce handshake timeout, bounded outbound queues, and slow-client eviction.
- [ ] **Scoped API Keys & Distributed Rate Limits**: Separate `api_keys` table (scopes, expiry, allowed IPs, rotation/revocation) and Redis-backed atomic rate limits with TTLs.

### 7.3 Real-Money Custody, Market-Maker Leases & Observability
- [ ] **Verified Custody & Double-Entry Reconciliation**: Replace demo collateral ledger in live mode with on-chain/provider receipt verification, finality checks, and immutable double-entry reconciliation.
- [ ] **Durable MM Fencing Leases & Portfolio Risk Service**: Move `mm_manager` ownership to distributed leases with kill switch, external reference-price freshness/divergence guards, and persisted decision/action audit logs.
- [ ] **Structured Telemetry & Keyset Pagination**: Add correlation-ID structured logs, OpenTelemetry/Prometheus metrics (order latency, queue lag, pool/WS health), and cursor/keyset pagination on public lists.

### 7.4 Frontend Contract & Design System Polish
- [ ] **Decimal-Safe Wire Contracts & Query Cache**: Migrate remaining `float` money payloads (`/collateral`, `clob.py`) to canonical decimal strings and adopt visibility-aware query caching.
- [ ] **Semantic Design Tokens & Touch/Motion Audit**: Replace hard-coded color classes with semantic theme tokens, refine `prefers-reduced-motion`, and verify WCAG 2.5.8 touch targets at 320px–375px.
