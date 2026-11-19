# DexBuilder Integration Readiness Handoff

Use this handoff to verify what works **today** (pre-permission) and what to run the moment DexBuilder activates `event_contracts` and WebSocket access for `DEXBUILDER_API_KEY` / `DEXBUILDER_BROKER_ID`.

---

## Phase A — Works Now (Pre-Permission)

Run the non-destructive readiness gate:

```bash
python scripts/verify_dexbuilder_readiness.py
```

What this verifies right now:
1. **Env & HMAC-SHA512 Signing** — `DEXBUILDER_API_KEY`, `DEXBUILDER_API_SECRET`, `DEXBUILDER_BROKER_ID`, and canonical `METHOD\nPATH\nQUERY\nSHA512(body)\nTIMESTAMP` signing.
2. **Offline Test Suites** — `tests/test_dexbuilder_auth.py`, `tests/test_dexbuilder_parity.py`, and `tests/test_dexbuilder_stream.py`.
3. **Public Live Market Feed** (`api.dexbuilder.com`, no auth required) — `get_time()`, `get_events(limit=3)`, `get_markets(status="active", limit=3)` powering `#/live` (`LiveMarketsPage`, `LiveMarketDetailPage`).
4. **Local Community & Seeded Markets** (Turso DB) — Community market creation, clarity score, AMM LP guards, and `TradeTicket` active-only guards work independently of DexBuilder auth.
5. **Advisory Auth Probe** — `check_credentials()` reports current upstream key status (`WARN` in pre-permission mode if `INVALID_KEY` / `401` / `403`).

---

## Phase B — Post-Permission Handoff (After DexBuilder Approves Key)

Once DexBuilder confirms `event_contracts` permission on your API key/broker ID:

1. **Confirm `.env` values**:
   - Ensure `DEXBUILDER_API_KEY`, `DEXBUILDER_API_SECRET`, and `DEXBUILDER_BROKER_ID` match the approved prediction-markets credentials.
   - Ensure `DEXBUILDER_FORCE_DRY_RUN` is unset or `false` when ready for live order routing.
2. **Run strict live gate**:
   ```bash
   python scripts/verify_dexbuilder_readiness.py --live
   ```
   All checks (`Signed Auth Probe`, `Broker Platform Assets`, `Broker Account Book`, `Broker WS Endpoint`) must exit `0`.
3. **Smoke-test UI routes**:
   - `#/live` -> open an active market -> verify live order book + WebSocket stream (`/api/v4/prediction/live/ws`) instead of polling fallback.
   - `Portfolio` -> `Broker Account` tab -> verify `assets`, `account_book`, `deposit-history`, `withdraw-history`, and `claims` load without `DEXBUILDER_UPSTREAM_UNAUTHORIZED`.
   - Place and cancel a minimum-size test order on `LiveTradeTicket` (`POST/DELETE /api/v4/dexbuilder/orders`).

---

## Phase C — Optional Demo Cleanup

After live DexBuilder official events are flowing:
- Archive or purge local `tier='OFFICIAL'` seeded demo events in Turso (`fed-interest-rate-decision`, `us-presidential-election-2028`, `btc-150k-before-sept`, `nba-champion`, `seed-resolved-macro`) while keeping `tier='COMMUNITY'` markets intact.
- Run full backend + frontend verification before deploy:
  ```bash
  pytest -q
  cd frontend && npm run build
  ```
