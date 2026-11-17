# Dolymarket production-readiness audit

Audit date: 2026-11-17. Scope: backend, persistence, matching and market maker, API/authentication, real-time delivery, frontend, operations, and scale. Method: source review, migration/CI review, static frontend detector, and production frontend build. No application code changed.

## Executive decision

The repository has strong prototype foundations: typed FastAPI routes, Alembic migrations, Decimal-backed money fields, passkey/OAuth, database uniqueness constraints, a substantial test suite, and a passing frontend production build.

It is not safe for real money, multi-instance deployment, or millions of users. Matching, sequence allocation, WebSocket state, rate limits, and market-maker ownership are all process-local. Concurrent matching lacks an authoritative serial execution boundary.

| Priority | Count | Release implication |
|---|---:|---|
| P0 | 4 | Must close before real-money or multi-instance launch |
| P1 | 10 | Must close before public beta |
| P2 | 9 | Schedule during hardening/scale work |
| P3 | 2 | Polish after safety work |

## Audit health score

| Dimension | Score | Key finding |
|---|---:|---|
| Security integrity | 1/4 | Script-readable tokens, replayable HMAC, permissive defaults, and WebSocket gaps |
| Correctness and financial integrity | 1/4 | Matching is not globally serializable; fees may be under-collected |
| Market-maker safety | 1/4 | No durable ownership, independent fair value, or portfolio risk service |
| Frontend quality | 2/4 | Build passes, but accessibility, performance, and theming need hardening |
| Scale and operations | 1/4 | Process-local state prevents horizontal scale |
| Total | 6/20 | Poor: major production work required |

## P0 findings

### P0 — Matching is process-local; no global authoritative book

Location: app/engine/book.py lines 201-216; app/core/sequencer.py lines 12-37; app/ws/sequence.py lines 7-12; app/ws/manager.py lines 9-33; app/services/market_maker.py lines 302-380.

Impact: Multiple workers or pods will have different liquidity, price-time priority, stream sequences, and bot state. A restart loses book and sequence state. This can create inconsistent fills and financial loss.

Follow-up:

1. Make one sequenced matching partition authoritative for every token ID; route all commands for that token to its leader.
2. Persist order/fill events and durable per-partition sequences atomically.
3. Publish committed events through a transactional outbox to a durable broker such as Redis Streams or Kafka.
4. Move WebSocket fan-out and bot leases out of web-process memory.
5. Test two instances, restart/replay, and leader failover with identical final books and fills.

Acceptance: Commands sent through two instances produce exactly one deterministic fill stream and identical snapshots before and after restart.

### P0 — Concurrent matching has no serialization or maker-row lock

Location: app/engine/clob.py lines 266-327.

Impact: Concurrent takers may fill the same maker liquidity. Commits can overwrite filled amounts, double-spend locked collateral, or leave memory/database books inconsistent.

Follow-up: Prefer actor or partition serialization. Add ordered row locks, optimistic versions or conditional updates, deterministic account/position locking order, conflict retry, and PostgreSQL concurrency tests for overfill, oversell, cancel-vs-fill, idempotent retry, and deadlocks.

### P0 — Collateral remains a demo ledger, not custody/settlement

Location: app/api/v1/collateral.py lines 60-102; frontend/src/components/CashLedgerModal.tsx lines 91-95.

Existing guard: The demo deposit endpoint is guarded by ENABLE_DEMO_COLLATERAL and defaults to disabled when APP_ENV is production. It also accepts an Idempotency-Key. The frontend has a DexBuilderTransferModal for the separate on-chain signing flow.

Impact: This is a useful guard against direct demo-balance minting in a correctly configured production deployment. It does not make the local ledger a custody system: withdrawals still cannot prove delivery of real assets, and deployment configuration must be treated as a critical control.

Follow-up: Keep this explicitly demo-only and add a deployment test proving the endpoint is disabled in production. Real funds need signed provider/on-chain receipts, confirmation/finality, reconciliation, address controls, immutable double-entry journals, sanctions/KYC/AML policy, approval thresholds, and incident procedures. Production mode must fail closed.

Acceptance: No unverified deposit or withdrawal changes usable collateral; every approved movement reconciles to an external transaction and balanced journal.

### P0 — Market maker cannot safely run live

Location: app/services/market_maker.py lines 302-380, 481-526.

Impact: Duplicate bots can run, bot quotes can reinforce stale/manipulated local prices, and per-tick risk scans become slow/incomplete as desks grow.

Follow-up: Use durable scheduling with fencing lease; validated external oracle/reference data with freshness, confidence, and divergence guards; a portfolio/risk service; global kill switch; persisted decision/input/action records; and backtests/paper trading with outages, partial fills, queue position, fees, and toxic flow.

## P1 findings

### P1 — Fee collection silently truncates rather than rejects an unfunded fill

Location: app/services/collateral.py lines 85-88; app/engine/clob.py lines 232-236 and 448-457.

Impact: A buyer funded exactly to notional can fill while its fee disappears. Revenue and ledger truth diverge.

Follow-up: Reserve worst-case fees at order acceptance or include them in buying power; validate funds at fill; reject or resize by documented policy; synchronously ledger fees. Add invariant tests: no negative account, fees due equal fees journaled, and each fill balances.

### P1 — Self-trade prevention checks only the first maker

Location: app/engine/clob.py lines 219-230 and 266-310.

Impact: A trader can self-match after an external partial fill, inflating volume and incentives.

Follow-up: Choose/document cancel-aggressor, cancel-resting, decrement-and-cancel, or reject. Enforce it atomically for every candidate maker. Test a user-owned second/third matchable level.

### P1 — WebSocket events are published before commit

Location: app/engine/clob.py lines 336-352; app/db/session.py lines 116-123; app/ws/broadcaster.py lines 12-30.

Impact: Clients can see trades/depth that later roll back.

Follow-up: Use transactional outbox. Store events and durable sequences with the order transaction, relay only committed records, make consumers idempotent, and support snapshot-plus-cursor recovery.

### P1 — Browser session model permits long-lived token theft

Location: frontend/src/api/client.ts lines 432-458; app/core/security.py lines 36-38 and 57-68.

Impact: Any XSS can extract a 24-hour bearer token. Logout cannot revoke a copied token.

Follow-up: Use short-lived in-memory access token plus rotating/revocable refresh token in Secure, HttpOnly, SameSite cookies; CSRF protection; device/session management; issuer/audience validation and server revocation; CSP, HSTS, frame, referrer, permissions, and no-sniff headers.

### P1 — HMAC requests can be replayed; API key model is too thin

Location: app/core/security.py lines 140-171; app/api/deps.py lines 36-56; app/models/domain.py lines 40-51.

Impact: Captured signed mutations can replay within five minutes. One key lacks scopes, expiry, audit, overlap rotation, and IP policy.

Follow-up: Persist bounded-TTL nonce/idempotency key plus request hash for every mutation. Create a separate API-key table with opaque ID, secret verifier, scopes, expiry, status, allowed IPs, last-used metadata, audit, revoke/rotate support. Limit body size before signature verification.

### P1 — WebSocket admission/backpressure can be exhausted

Location: app/api/v4/ws.py lines 98-142; app/ws/manager.py lines 43-52.

Impact: Query JWTs leak to logs/history; idle pre-auth clients consume sockets; one slow client delays fan-out; no connection/message/subscription/buffer quota exists.

Follow-up: Use short-lived single-use WebSocket tickets or subprotocols, not URL tokens. Enforce origin/connection/message quotas, handshake timeout, ping/pong deadlines, bounded outbound queues, slow-client eviction, and broker-backed concurrent fan-out.

### P1 — Rate limiting and proxy/CORS policy are not production-safe

Location: app/core/ratelimit.py lines 19-47; app/main.py lines 61-88 and 202-213.

Impact: Limits reset per worker/restart, bucket keys can grow unbounded, attacks bypass per-process limits, and wallet auth endpoints are missing from the auth rate-limit list.

Follow-up: Redis/edge atomic rate limits with TTLs and route-cost/per-IP/account/key quotas; include all auth ceremonies; require explicit CORS origins, trusted proxy CIDRs, public URL, and HTTPS at startup.

### P1 — SIWE origin policy is client-influenced

Location: app/api/v1/auth.py lines 155-169 and 209-250.

Impact: Login messages do not meet strict relying-party EIP-4361 policy, complicating phishing protection/audit.

Follow-up: Derive canonical domain/URI/allowed chain IDs from trusted config, enforce Origin, use a standards-compliant SIWE verifier, atomically consume one-time challenges, and rate limit them.

### P1 — Database lifecycle can silently produce wrong production schema

Location: app/db/session.py lines 20-22 and 125-133.

Impact: Startup can create schema outside Alembic history or use local non-durable SQLite when configuration is absent.

Follow-up: Run Alembic only in deploy jobs; remove production auto-DDL; fail startup without explicit PostgreSQL/dependency/readiness configuration. Retain SQLite only for tests/demo.

### P1 — Operational failures are concealed

Location: app/main.py lines 151-180; app/services/market_maker.py lines 584-586.

Impact: Reward/bot/financial failures can remain undetected.

Follow-up: Structured logs with correlation IDs/redaction; metrics/traces/alerts for order latency, fills, queue lag, risk limits, dependencies, database pools, and WebSocket health; immutable audit logs; runbooks and on-call escalation.

## P2 findings

### P2 — Queries and offset pagination will degrade with history

Location: app/api/v4/public.py lines 93-130 and 178-204; app/engine/book.py lines 80-89; multiple settlement/copy/desk services use unbounded all calls.

Impact: Deep pages and active books grow increasingly expensive in latency and memory.

Follow-up: Opaque keyset cursors, bounded list endpoints, aggregates/read models, composite indexes verified with PostgreSQL explain plans, event retention/partitioning, response-size budgets, and load tests.

### P2 — Financial values cross contracts as float

Location: app/api/v1/collateral.py lines 49-55, 76-81, 97-100; app/engine/clob.py lines 301-303.

Impact: Precision artifacts and reconciliation disagreement become possible.

Follow-up: Return canonical decimal strings or integer minor units; parse/format with decimal-safe frontend utilities; version the contract deliberately.

### P2 — Frontend eagerly ships pages and over-polls

Location: frontend/src/App.tsx lines 19-37; TradeTicket.tsx line 61; HeroVisual.tsx line 103; RecentTrades.tsx line 50; DeskMarketMakerPanel.tsx line 57.

Evidence: Production build succeeds, but emits 467 KB raw / 126.95 KB gzip main JavaScript, plus vendor/charts chunks.

Follow-up: Adopt maintained routing with route-level lazy chunks; defer charts/admin code; set bundle budgets; use a query cache for deduplication, cancellation, stale times, visibility-aware polling, and WebSocket invalidation. Measure Web Vitals on representative devices.

### P2 — Dialog and form accessibility is incomplete

Location: frontend/src/auth/AuthProvider.tsx lines 244-251; frontend/src/components/CashLedgerModal.tsx lines 40-44 and 96-102; frontend/src/components/WalletConnectModal.tsx lines 100-107.

Impact: Dialogs lack dialog role/name/modal state, focus trap/restore, and Escape; cash amount lacks a label. This is a WCAG keyboard/name-role-value risk.

Follow-up: Build one tested dialog primitive with semantic role, accessible name/description, focus handling, Escape, scroll lock, and live async status. Label every input. Run Axe plus keyboard/screen-reader tests.

### P2 — Reduced-motion rule removes useful feedback globally

Location: frontend/src/index.css lines 66-75.

Impact: Making every transition 0.01ms can flash away meaningful state changes.

Follow-up: Remove decorative motion component-by-component but retain immediate non-motion cues for dialogs, loading, selection, and errors. Test OS reduced motion.

### P2 — Theming is inconsistent

Location: frontend/src/index.css lines 3-37; frontend/src components/pages.

Evidence: Tokens exist, but a static scan found roughly 1,687 hard-coded color utility/value occurrences.

Follow-up: Define semantic surface/text/border/positive/negative/warning/focus/chart tokens; migrate shared UI first; validate contrast; decide on light/high-contrast support.

### P2 — Compact controls need touch review

Location: frontend/src/components/TradeTicket.tsx lines 463-496; WalletConnectModal.tsx lines 124-129.

Follow-up: Measure at 320px, 375px, tablet, and increased text scale; meet WCAG 2.5.8 size/spacing, use aria-pressed for toggles, and touch-test trading/wallet/modal flows.

### P2 — Market-maker model needs research-grade controls

Location: app/services/market_maker.py lines 102-106, 513-526, 605-634.

Follow-up: Validate input schema/range/freshness/version; calibrate and version models per market class; calculate audited daily PnL/global stress; sequence cancel-replace with stale-quote timer; property-test bid below ask/limits; replay adverse-flow and failures.

### P2 — Architecture documentation has drifted

Location: docs/improve.md.

Impact: The document describes database re-querying and no reconnect backoff, while app/engine/book.py has in-memory books and frontend/src/api/reconnectingSocket.ts has reconnect support.

Follow-up: Replace with ADRs for authoritative state, event flow, durability, deployment modes, threat model, and matching/custody/MM architecture. Require ADR plus invariant tests for financial changes.

## P3 findings

### P3 — Generic decorative grid

The frontend detector reports a decorative grid advisory at frontend/src/index.css lines 97-103. Remove it or connect it to actual market data. Not release-blocking.

### P3 — Custom hash routing limits ergonomics

Location: frontend/src/App.tsx lines 39-57.

Follow-up: Migrate during route splitting to typed routes with per-route loaders/errors and improved history/analytics semantics.

## What to preserve

- Native bcrypt and fail-fast JWT-secret behavior outside explicit insecure test mode.
- OAuth short-lived exchange codes rather than JWT callback URLs.
- Database-backed order idempotency uniqueness/request hash in app/models/domain.py lines 222-241.
- Numeric/Decimal core money fields.
- Constraints for positions, desks, followers, copy jobs, OAuth identities, and passkeys.
- Typed frontend API client, error boundary, focus-visible styling, reconnecting socket abstraction.
- CI coverage of SQLite, PostgreSQL migration application, backend tests, and frontend build.

## Target architecture for millions of users

1. Safety baseline: close P0/P1 items, demo-only collateral, explicit production configuration, audit logs, transactional outbox.
2. Correctness: authoritative matching, durable events/sequences, PostgreSQL concurrency/restart/reconciliation tests.
3. Horizontal reads/realtime: broker fan-out, cache/read models, keyset pagination, distributed rate limits, WebSocket gateway.
4. Shard matching: deterministic token partitions with leader fencing and snapshot/replay recovery; preserve price-time priority per partition.
5. Regulated production: independent security review, penetration test, custody/oracle/legal/compliance programs, backup/restore, RPO/RTO, disaster-recovery drills.

## Follow-up execution order

1. Create a contract/spec and ADR for matching/custody scope before code changes.
2. Implement authoritative matching plus transactional outbox; prove PostgreSQL concurrency and restart safety.
3. Fix collateral/fee invariants and self-trade behavior; add reconciliation tests.
4. Harden sessions, HMAC replay, SIWE, rate limits, and WebSockets.
5. Replace process-local runtime state with broker/lease-backed components.
6. Keep market making dry-run until risk, calibration, replay, and kill-switch criteria pass.
7. Improve frontend accessibility/performance after backend contracts stabilize; validate mobile and assistive-technology flows.

## Verification performed

| Check | Result |
|---|---|
| Frontend production build | Passed: TypeScript and Vite completed successfully |
| Frontend implementation detector | One advisory only: decorative CSS grid |
| pytest -q | Passed in the provisioned environment: 197 tests |
| ruff check app tests | Passed in the provisioned environment |

CI is configured to install and run backend checks. Follow-up work should rerun pytest, Ruff, Alembic migration verification, and targeted concurrent-load tests after substantive changes.

