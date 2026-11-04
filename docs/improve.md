# Production Architecture Improvements: Prediction Market Platform

This document outlines architectural and engineering improvements identified for the full-stack prediction market application scaffolded in `opencode-worker/`.

---

## 1. High-Performance CLOB Engine & In-Memory Matching

### Current Implementation
- `app/engine/clob.py` re-queries the database for resting orders on every order placement using `AsyncSession.execute(select(Order)...)`.
- Matching logic iterates through SQL query rows and issues individual updates.

### Recommended Changes
1. **In-Memory OrderBook with Async DB Sync**:
   - Maintain active orderbooks in memory as dual Priority Queues / Red-Black Trees (bids descending, asks ascending) indexed by price ticks.
   - Match aggressive orders against the in-memory book at microsecond latency.
   - Emit execution fills to an async queue/channel for batched database persistence (write-behind pattern).
2. **Deterministic Sequence Numbering**:
   - Assign monotonically increasing `sequence_id` to every matched fill and orderbook delta so WebSockets clients can detect dropped packets and request catch-up snapshots.

---

## 2. Concurrency Control & Balance Row Locking

### Current Implementation
- Balance checks query `CollateralAccount` without row-level locks, creating potential race conditions under high concurrent order submission from the same account.

### Recommended Changes
1. **Row-Level Locking**:
   - In `app/api/v4/orders.py` and `app/services/collateral.py`, use `.with_for_update()` when checking and locking collateral:
     ```python
     stmt = select(CollateralAccount).where(CollateralAccount.user_id == user_id).with_for_update()
     ```
2. **Idempotency Keys**:
   - Accept an optional `X-Idempotency-Key` header on `POST /api/v4/prediction/orders` to safely handle network retries from UI or algorithmic traders.

---

## 3. Real-Time Streaming & WebSocket Client Resilience

### Current Implementation
- Public and private WebSockets broadcast updates cleanly, but client reconnection handling in frontend relies on native browser event handlers without exponential backoff or state synchronization.

### Recommended Changes
1. **Client Reconnection with Jitter**:
   - Implement an exponential backoff reconnect policy (`min: 1s`, `max: 30s`, random jitter `0-20%`) in `frontend/src/api/` WebSocket wrappers.
2. **Orderbook Resync on Reconnect**:
   - Upon reconnection, request a fresh L2 orderbook snapshot via `GET /api/v4/prediction/tokens/{id}/order_book` before reapplying incremental WebSocket deltas to eliminate stale state.
3. **Heartbeat Liveness**:
   - Send ping frames every 30 seconds; terminate dead sockets if pong is not received within 10 seconds.

---

## 4. Frontend Trading UX & Charting

### Current Implementation
- `frontend/src/pages/EventDetailPage.tsx` provides order entry, live depth ladders, and probability curves.

### Recommended Changes
1. **Lightweight Charts Canvas Integration**:
   - Embed TradingView Lightweight Charts (`lightweight-charts`) for hardware-accelerated rendering of 1m/5m/1h OHLCV candlesticks with volume histogram.
2. **Keyboard Shortcuts for Traders**:
   - Add standard hotkeys: `B` for Buy, `S` for Sell, `Esc` to close modal/drawer, `Enter` to submit order.
3. **Optimistic UI Updates with Toast Rollback**:
   - Render pending limit orders immediately in the open orders table with a "Pending" pulse, reverting with toast error if the server returns 400/409.

---

## 5. Security & Multi-Tenancy Hardening

### Recommended Changes
1. **HMAC Request Signature Verification**:
   - For algorithmic API traders, implement standard API key + HMAC-SHA256 signature verification over `TIMESTAMP + METHOD + PATH + BODY`.
2. **Rate Limiting**:
   - Add token-bucket rate limiting per IP / API key (e.g. 50 orders/second for authenticated users, 100 requests/minute for public endpoints).
