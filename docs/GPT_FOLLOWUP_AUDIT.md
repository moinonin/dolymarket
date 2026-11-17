# Follow-up production-readiness audit

Audit date: 2026-11-17. This is a delta audit against recommendations in docs/GPT_AUDIT.md. It records implemented controls, remaining blockers, and regressions. No application code changed.

## Outcome

The codebase has materially improved. It now includes durable token sequence/outbox tables, post-commit callbacks, database maker-row locks, local per-token locking, second-level self-trade protection, fee-headroom rejection, auth ceremony rate-limit coverage, WS tickets/timeouts, refresh-token rotation, production SQLite rejection, metrics, request IDs, route splitting, and targeted regression tests.

The application is still not ready for multi-instance exchange matching or real custody. The key reason is wiring: the new partition lease is used by the market maker but not by order submission, and the in-memory book remains a process-local source of matching truth.

| Previous recommendation | Status | Assessment |
|---|---|---|
| Serial matching and durable sequence | Partial | Per-process lock and durable sequence added; global command leadership not enforced |
| Transactional outbox | Partial | Events are written before commit and relayed post-commit; relay claim/idempotency is not safe across workers |
| Fee shortfall | Closed for tested BUY path | Fill rejects insufficient fee headroom |
| Second-level self-trade | Closed | Matching stops before own resting order |
| Demo collateral guard | Improved | Demo deposit remains environment-gated |
| Browser session security | Partial | Refresh rotation exists, but SPA still persists access JWT in local storage |
| HMAC replay | Improved | Targeted replay test exists; key model remains one key per user |
| WebSocket query-token/idle auth | Improved | Single-use tickets and a handshake timeout exist; query-token fallback and local fan-out remain |
| Rate limiter memory growth | Improved | Memory is bounded; limiter remains per process |
| Production schema lifecycle | Improved | Production avoids startup create_all and rejects SQLite by default |
| Frontend route bundle | Closed | Production build now code-splits routes |

## Remaining P0 blockers

### P0 — Partition lease is not enforced by matching commands

Evidence: app/services/outbox.py provides claim_partition_lease, and app/services/market_maker.py uses it. app/engine/clob.py submit_order does not call claim_partition_lease or verify a fencing token before reading/mutating app/engine/book.py. The registry in app/engine/book.py lines 197-233 is still process-local.

Impact: Two web processes can both accept commands and match against separate book caches. Durable sequence allocation does not restore global price-time priority or prevent split-brain matching.

Required follow-up:

1. Route each token command to a designated matching leader, or have a matching worker consume a single ordered command stream for its partition.
2. Acquire/renew a lease before every partition command and attach a monotonically increasing fencing token to persisted updates.
3. Reject/retry commands at non-leaders; do not silently let API processes match locally.
4. Make snapshots/read APIs derive from the authoritative partition state or replayed read model.
5. Add a two-process integration test that proves one process cannot fill stale liquidity after lease loss.

Acceptance: Run the same token through two independent processes; only the current lease holder can mutate it, and loss/takeover cannot create duplicate fills or divergent depth.

### P0 — The outbox relay is not safe for concurrent relayers

Evidence: app/services/outbox.py relay_pending_outbox selects unpublished rows without row locks, SKIP LOCKED, a lease, or a claim state; it broadcasts before marking rows published. The outbox model has no event-id consumer contract or unique token-sequence constraint.

Impact: Multiple pods can relay the same records. A broadcaster failure after delivery but before the published update also redelivers. At-least-once delivery is acceptable only with idempotent consumers; current public WebSocket clients do not receive a documented immutable event ID.

Required follow-up:

1. Claim rows atomically using SELECT FOR UPDATE SKIP LOCKED or an outbox delivery lease with retry deadline.
2. Publish immutable event IDs and durable partition sequence numbers to all consumers.
3. Make fan-out/read-model consumers idempotent by event ID.
4. Add a uniqueness constraint for the intended ordering identity, normally token ID plus partition sequence, and clarify ordering for user-only events.
5. Run concurrent-relayer and crash-between-send-and-mark tests on PostgreSQL.

## Remaining P1 findings

### P1 — Refresh-token backend is not integrated into browser session flow

Evidence: auth backend mints refresh cookies in app/api/v1/auth.py, but frontend/src/api/client.ts lines 432-458 still stores the access token in localStorage. Its logout function only clears local storage; frontend/src/auth/AuthProvider.tsx invokes it without making the server logout request.

Impact: XSS can still steal the access token, refresh may not be used automatically after expiry, and browser logout may leave the refresh cookie/session active.

Required follow-up: Keep access token only in memory, issue fetch requests with cookie credentials where required, add a single-flight refresh interceptor, call server logout before clearing client state, and add CSRF protection/origin validation for cookie-authenticated mutations. Add browser-level tests for refresh, retry, logout, and page reload.

### P1 — Real deposit endpoint accepts a caller-supplied amount/transaction hash without chain verification

Evidence: app/services/collateral.py lines 128-146 uses amount, tx hash, and chain ID supplied by the request. It prevents a repeated reference only by querying a ledger column; there is no database unique constraint on reference and no RPC/indexer receipt validation.

Impact: This is replay-resistant only in the happy path. It does not establish that the stated transaction transferred the stated USDC amount to a controlled destination, belongs to the authenticated user, is confirmed, or is not concurrently credited twice.

Required follow-up: Verify receipt/logs through a trusted chain provider or indexer, enforce expected chain/token/recipient/sender/amount/finality, persist an immutable unique chain-event identity under a database uniqueness constraint, and reconcile against the provider. Do not label this real custody until withdrawal policy and external reconciliation are implemented.

### P1 — Fee fix is late and can invalidate an already-mutated in-memory book

Evidence: app/engine/clob.py locks only price times amount at lines 232-235. The insufficient-fee check occurs during _execute_fill after maker state/book mutation has begun at lines 467-492. Exception recovery invalidates the local book, but rejection is discovered at fill time.

Impact: The tested exact-notional case is rejected, but the system has not reserved a maximum fee up front. This complicates partial fills and makes the command path rely on rollback after mutable work.

Required follow-up: Reserve the worst-case fee when accepting a BUY limit order, use that reserved amount for partial fills/cancel release, and write a fee ledger entry on every executed fee. Property-test partial fills, multiple makers, cancellation, and exact available balances.

### P1 — API keys remain single-user, global-secret-derived credentials

Evidence: app/models/domain.py User has one api_key digest; app/api/v1/auth.py rotates/revokes that one value.

Impact: There are no per-key scopes, expiry, IP policy, audit trail, overlap rotation, or emergency targeted revocation. Hashing all keys with JWT_SECRET also couples credential verification to JWT-secret rotation.

Required follow-up: Introduce an ApiKey entity with opaque ID, per-key salted verifier, scopes, expiry, status, last-used data, allowed network policy, audit events, multiple concurrent keys, and a key-encryption/pepper rotation plan.

### P1 — WebSocket protections still have insecure fallback and local scaling limits

Evidence: app/api/v4/ws.py lines 100-150 still accepts token query parameter and an auth frame containing token. app/ws/manager.py remains an in-process connection list and serial broadcaster.

Impact: Query-token leakage remains possible for callers using fallback. Public/private presence and broadcast do not scale across pods; a slow socket can still delay a local broadcast.

Required follow-up: Remove token-query/frame fallback after ticket migration, use gateway-managed authenticated sockets, bounded per-client queues, backpressure/slow-consumer eviction, broker-backed fan-out, and per-user/IP connection/message/subscription quotas.

### P1 — Rate limit and token/session revocation are bounded but not distributed

Evidence: app/core/ratelimit.py and app/core/security.py retain bucket, revoked-JTI, and WS-ticket dictionaries in process memory.

Impact: Limits, revocations, and tickets do not work consistently across pods and reset on restart. This weakens abuse protection and logout/revocation guarantees in a horizontally scaled deployment.

Required follow-up: Move all three concerns to Redis or an equivalent shared TTL store, with atomic consume/compare operations and availability/fail-closed policy for sensitive endpoints.

### P1 — Production CORS remains wildcard unless deployment configuration overrides it

Evidence: app/main.py lines 210-223 still defaults CORS_ALLOW_ORIGINS to wildcard in all modes.

Impact: A missing production variable results in permissive cross-origin access. This conflicts with the new cookie-based refresh design if credentials are later enabled.

Required follow-up: Make explicit origin allowlist mandatory in production startup, validate exact HTTPS origins, and test deployment configuration failure.

## Remaining P2 findings

### P2 — Cross-process correctness test is not actually cross-process

Evidence: tests/test_distributed_outbox.py tests two leases and concurrent HTTP calls using one test application/process. It does not create independent registries/processes or test command routing after leader failover.

Follow-up: Add PostgreSQL-backed integration tests that start two worker processes or separate engine registries against one database and exercise stale cache/lease takeover.

### P2 — In-memory process sequencer still appears in order book snapshots

Evidence: app/engine/book.py lines 108-149 and 182-193 use app/core/sequencer.py for book snapshots, while outbox partitions allocate a different durable sequence.

Impact: A snapshot can expose a process-local sequence that has no stable relationship to durable partition ordering after restart/failover.

Follow-up: Replace book sequence fields with the committed durable partition sequence or explicitly separate local implementation counters from public protocol fields.

### P2 — Financial APIs/events still serialize Decimal as float

Evidence: app/engine/clob.py lines 313-314, 354-355, 549-550, and 563-565 emit float values. The original public collateral endpoints also expose float balances.

Follow-up: Use canonical decimal strings or integer minor units for all financial contracts, including WebSocket payloads; version schemas and add precision regression tests.

### P2 — Real production DDL is improved but migration readiness is not fully enforced

Evidence: app/main.py skips init_db in production and rejects SQLite, which is correct. It does not verify the deployed Alembic revision, broker, or external dependency readiness before serving traffic.

Follow-up: Separate migration deploy job, readiness endpoint that verifies schema head and critical dependencies, and rollout gate that blocks incompatible application/schema combinations.

### P2 — Observability is an initial metric surface, not production telemetry

Evidence: app/main.py exposes in-process request/connection/bot counters at metrics. Counters reset per worker and have no latency histogram, error dimensions, queue/outbox lag, external dependency health, structured log correlation, or alert rules.

Follow-up: Export standard Prometheus counters/histograms/gauges, OpenTelemetry traces, durable audit logs, redaction, dashboards, SLOs, and alerts. Never scrape a single pod as if it were global truth.

### P2 — Market maker is safer but still lacks independent pricing/risk architecture

Evidence: it has lease fencing and stale-feed/kill-switch tests, but its primary book mid is still local and desk exposure scans positions each tick.

Follow-up: move pricing inputs to validated reference feeds, build portfolio/risk projections and stress limits, persist model versions/decisions, and require paper-trading/backtest acceptance before live execution.

### P2 — Accessibility improvements from the prior audit remain unverified

Evidence: the frontend detector reports no implementation-integrity advisories and route splitting is now effective, but modal components still use overlay div patterns and access-token storage is unchanged. No automated accessibility dependency or test suite is present.

Follow-up: introduce a dialog primitive, add role/dialog semantics/focus trap/Escape/restore, label amount controls, test keyboard/screen reader and 320px touch target layout, then add automated Axe checks to CI.

## Closed or materially improved recommendations

- Per-process concurrent overfill: materially improved by token lock plus maker row locking; verified by targeted concurrent test.
- Second-level self-trade: closed in matching path and regression test.
- Exact-notional BUY fee shortfall: rejected by regression test.
- Wallet endpoints now appear in authentication rate-limit policy.
- SIWE client-provided domain is no longer reflected in issued challenge according to regression test.
- Demo collateral is explicitly gated; verified-deposit/reconcile endpoints and regression tests exist.
- Post-commit event handoff is improved through transactional outbox and callback.
- Production startup avoids create_all and rejects SQLite unless explicitly overridden.
- WS ticket and bounded pre-auth handshake are implemented.
- Frontend route splitting is successful: current production entry is about 31.43 KB gzip; no frontend detector findings.

## Verification

| Check | Result |
|---|---|
| frontend production build | Passed in this audit |
| frontend detector | Passed: no findings |
| pytest | Local workspace cannot import pytest_asyncio; prior provisioned result reported by user: 197 passing tests |
| ruff | Not available in this workspace; prior provisioned result reported by user: passed |

## Next execution order

1. Enforce one authoritative matching leader/token before accepting commands in more than one process.
2. Make outbox delivery safe for multiple relayers and consumers idempotent.
3. Finish browser refresh-cookie integration and remove access JWT local storage.
4. Convert deposit verification into actual chain/provider receipt validation with database-enforced uniqueness.
5. Move rate-limit, ticket, and revocation state to shared infrastructure.
6. Close remaining decimal, accessibility, operational telemetry, and risk-model work.

