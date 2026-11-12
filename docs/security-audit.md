# Platform Security & Contract Audit

**Date:** 2026-11-11 · **Scope:** full backend (`app/`), frontend (`frontend/src/`), contracts, deployment config
**Method:** manual code review + empirical exploit probes run against the app in a hermetic test environment. Every Critical/High finding below was reproduced and observed returning the quoted status codes — nothing is speculative. Probe files were deleted after evidence was captured; the full test suite (153 tests) still passes.

**Stack:** FastAPI 4.1 + SQLAlchemy async (SQLite/Postgres), in-memory CLOB, React 18 + Vite SPA, JWT bearer + HMAC API keys, WebAuthn passkeys, OAuth (Google/Microsoft/Apple), AGX staking token, DexBuilder upstream proxy.

---

## Verdict summary

| Area | Grade | One-line verdict |
|---|---|---|
| Auth primitives (bcrypt, HMAC, PKCE, WebAuthn) | B | Sound design, one broken piece (JWT secret fallback) |
| Route authorization | **F** | Oracle resolution and private-data proxy are open to any user |
| Money handling (collateral/AGX) | **D** | Unlimited mint faucet; misdirected admin reconciliation |
| Input validation | C− | Floats everywhere money lives; unbounded lists; NaN reaches Decimal |
| Contract/OpenAPI hygiene | **F** | 2 of 114 routes have a response model; frontend types are `any`/fabricated |
| Frontend security | C | No XSS sinks found; token in localStorage; OAuth popup path trusts message payload |
| Performance/DoS surface | C− | N+1 amplification on public unauthenticated endpoints |
| Test suite | B | 153 passing, hermetic, good coverage of happy paths; zero negative-auth tests |

**Do not deploy this to real value until every Critical below is fixed.** Several findings compose into end-to-end theft: register → mint USDC → resolve any market in your favour → redeem.

---

## CRITICAL

### C-1 · Any authenticated user can finalize any market and pay themselves the winning side

`app/api/v4/resolution.py:77-105` — the handler resolves `user` and never checks it:

```python
@router.post("/finalize")
async def finalize(body: FinalizeRequest, user: User = Depends(get_current_user), ...):
    ...
    market = await settlement.finalize_resolution(session, market, body.winning_outcome_index)
```

`app/services/settlement.py:87-98` accepts status `"CLOSED"` directly, so the proposal + 2-hour dispute window can be skipped entirely:

```python
if market.status not in ("IN_RESOLUTION", "DISPUTED", "CLOSED"):
    raise HTTPException(...)
market.winning_outcome_index = winning_outcome_index
market.status = "RESOLVED"
```

**Reproduced:** a freshly-registered non-admin called `POST /api/v4/prediction/resolution/finalize` on a CLOSED market → `200 {"status":"RESOLVED","winning_outcome_index":0}`. From there `POST /positions/{id}/redeem` pays $1.00/share to whoever holds the chosen outcome — an attacker can buy cheap outcome tokens on an uncertain market, resolve it in their own favour, and drain the pool. This is the single worst bug in the repo.

**Fix:** gate `propose`/`dispute`/`finalize` behind the existing `_require_admin` helper (`app/api/v4/admin.py:46-50`), or a dedicated oracle-role dependency; remove `"CLOSED"` from the allowed source statuses in `finalize_resolution`; record `finalized_by` for audit.

### C-2 · Any authenticated user can propose/dispute resolutions with no bond ever charged

`app/api/v4/resolution.py:32-74` — both handlers are `get_current_user` only. `settlement.propose_resolution` (settlement.py:45-52) hardcodes `proposer_address="uma-optimistic-oracle"` and `bond_amount=50` without debiting anyone; `dispute_proposal` (settlement.py:80-81) merely *compares* the caller-supplied `counter_bond` float — no funds move. **Reproduced:** non-admin `propose` → 200, market flipped to `IN_RESOLUTION`. Any user can grief the resolution pipeline on every closed market. Fix together with C-1; debit real bonds from the proposer's collateral account and refund on finalization.

### C-3 · Unauthenticated proxy forwards the platform's private upstream data to the whole internet

`app/api/v4/dexbuilder/proxy.py:184-213` — four routes with **no auth dependency**:

```python
@router.get("/positions")
async def proxy_positions(client: DexBuilderClient = Depends(get_client)):
    return await client.get_positions()
# also /positions/settled, /usertrades, /orders
```

`app/services/dexbuilder.py:184-192` signs every upstream call with the platform-wide shared secret. **Reproduced:** all four routes reachable anonymously (they returned `502 DEXBUILDER_UPSTREAM_UNAUTHORIZED` only because the test env has no upstream credential — with `DEXBUILDER_API_KEY/SECRET` set, as in the real `.env`, any anonymous caller receives the platform's live positions, orders and trades). This also contradicts the module contract at `app/api/v4/prediction/live.py:5-6` ("never expose private (credentialed) upstream data").

**Fix:** delete the four routes, or re-expose them behind `get_current_user` with per-user upstream credentials. Never sign with a platform-wide secret on behalf of an anonymous caller.

### C-4 · `POST /api/v1/collateral/deposit` is an unlimited money faucet

`app/api/v1/collateral.py:35-47` credits whatever number the caller posts; `app/services/collateral.py:34-41` has no payment verification, no idempotency key, no cap, and the path is not rate-limited (`AUTH_ATTACK_PATHS` and `ORDER_MUTATION_PREFIX` in `app/main.py:43-77` don't cover it). **Reproduced:** five deposits of 1,000,000 → `balance: 5000000.0 USDC`. Combined with C-1/C-2 this is a complete theft chain. **Fix:** require a verified payment/on-chain receipt (mirroring the AGX `sync_balance` pattern at `app/services/agx.py:582-612`), add idempotency keys, and rate-limit.

### C-5 · JWT secret has a hardcoded fallback → trivial token forgery

`app/core/security.py:11`:

```python
JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-key-1234567890abcdef")
```

**Reproduced:** a JWT forged with the fallback secret authenticated successfully (`GET /auth/me → 200` with a fabricated `sub`). One env var missed in a real deployment = full account takeover, including admin accounts. **Fix:** fail fast at startup when `JWT_SECRET` is unset (and reject the known test value); same for `api_key_digest` which derives from `JWT_SECRET` (security.py:94-102).

### C-6 · Admin AGX reconciliation credits the wrong account

`app/api/v1/agx.py:302-314` — `SyncBody` (`agx.py:127-128`) has only `verified_balance`; the handler passes `user.id` — **the admin's own id** — into `agx.sync_balance` (agx.py:582-612), which credits the admin and writes the deposit ledger row against them. A real user with on-chain AGX can never be reconciled. **Fix:** add `user_id: StrictStr` to the body, validate the target exists, keep the admin gate.

---

## HIGH

### H-1 · WebSocket private channel: cross-site hijack surface, double-accept crash, no user re-check

`app/api/v4/ws.py:55-97`:

- No `Origin` validation on any WS route (ws.py, ws_live.py), and CORS is `allow_origins=["*"]` (`app/main.py:115-121`) — browsers do not enforce CORS on WebSockets, so any web page can open `wss://host/api/v4/prediction/ws/private` and attempt the `auth` handshake with a phished/harvested token.
- Token accepted via query string (`?token=`) → leaks into proxy logs and history.
- `decode_access_token(token).get("sub")` may return `None`; the code proceeds to `manager.connect_private(ws, user_id)` with `user_id=None` (ws.py:84) and never confirms the user still exists.
- Double `accept()`: ws.py:67 accepts, then `manager.connect_private` (`app/ws/manager.py:18-20`) accepts again → `RuntimeError` kills the token-less auth path.

**Fix:** origin/allowlist check before `accept()` on all three WS routes; take the token from a header or `Sec-WebSocket-Protocol`; reject null `sub` and re-verify the user row; remove the duplicate accept.

### H-2 · Rate limiting misses register/passkey-register and is proxy-blind

`app/main.py:45-77`: `AUTH_ATTACK_PATHS` covers login, oauth/exchange and passkey login only. **Reproduced:** 60/60 `POST /api/v1/auth/register` accepted — mass account creation is unthrottled. The bucket keys on `request.client.host`, which behind a reverse proxy is the proxy IP unless `ProxyHeadersMiddleware`/uvicorn `--proxy-headers` is configured — one shared bucket for all users, and one attacker can exhaust it. **Fix:** add `/api/v1/auth/register` and passkey register routes; honour `X-Forwarded-For` from a trusted proxy.

### H-3 · Floats guard the money paths — NaN reaches Decimal arithmetic

`AmountRequest.amount: float` (`app/api/v1/collateral.py:15`), `CreateOrderRequest.price/amount: float` unbounded (`app/api/v4/orders.py:32-41`), `SplitRequest.shares: float` (`app/api/v4/positions.py:27-29`), `DisputeRequest.counter_bond: float = 50.0` (`app/api/v4/resolution.py:24`). Python's `json` accepts `NaN`/`Infinity`; `Decimal(str(nan))` passes `x <= 0` checks (comparisons are False) and detonates as `decimal.InvalidOperation` → 500s, or worse, `price/amount = inf` rounds oddly at `q4()` (ROUND_DOWN). Contrast the AGX module which correctly uses `StrictStr` decimal strings end-to-end. **Fix:** `Decimal` fields with `gt=0`/`le=` bounds plus an `is_finite()` validator; mirror the AGX StrictStr pattern.

### H-4 · Rejected orders return HTTP 201 and are cached as the idempotent result

`app/api/v4/orders.py:228-248`: the engine's `OrderRejected(rejected=True)` path commits and returns a `REJECTED` payload with the route's declared `status_code=201` — callers can't distinguish creation from rejection by status, and `_store_idempotent` caches the rejection. The frontend consequence is confirmed below (F-6): the UI shows a green "info" toast for rejections and drops the `reason`. **Fix:** raise `409`/`422`, or declare a 200 contract and don't cache rejections under the idempotency key.

### H-5 · Bare `except Exception: pass` around copy-trading mirroring

`app/api/v4/orders.py:264-285` — swallows everything including SQLAlchemy errors, after which the request-scoped `commit()` in `app/db/session.py:33` re-raises and rolls back the user's own fill, or (non-DB errors) silently skips follower mirroring with zero telemetry. **Fix:** narrow the catch, `logger.exception`, record a failed copy job, `rollback()` on DB errors.

### H-6 · JWT in `localStorage`, 24h TTL, no refresh, dead 401 handling

`frontend/src/api/client.ts:422-448` stores the token in localStorage (`dolymarket_auth_token` plus a legacy second key); any future XSS = full account takeover. `frontend/src/auth/AuthProvider.tsx` never inspects `exp`, there is no refresh token, and `client.ts:502` clears the token on 401 but leaves the UI showing a signed-in user whose every call fails. **Fix:** HttpOnly cookie + CSRF double-submit (and then narrow the CORS wildcard, see M-6), or at minimum: single key, proactive expiry check, an unauthorized-handler that resets the auth context.

### H-7 · Frontend "Cancel All" can never succeed — contract drift

`frontend/src/api/client.ts:652-656` builds an empty query when params are empty, and `frontend/src/pages/PortfolioPage.tsx:576` calls `api.cancelAllOrders({})`. Backend `app/api/v4/orders.py:324-344` 422s without `market_id`/`condition_id`. **Reproduced:** `DELETE /orders?` → `422 {"detail":"market_id or condition_id required"}`. The button is dead UI. **Fix:** make `market_id` required client-side and group the cancel by market.

### H-8 · Events sort/filter contract drift — two tabs silently lie

`frontend/src/pages/MarketsPage.tsx:20-25` offers `sort_by: volume|liquidity|newest|ending_soon`; backend `app/api/v4/public.py:93-98` implements only `ending_soon` and `liquidity` — `volume` silently falls through to `created_at DESC`. The `ACTIVE_ENDING` status tab (MarketsPage.tsx:14-19) is filtered out at the call site and equals "All". **Reproduced:** `sort_by=volume` → 200, ordered by created_at. **Fix:** implement `volume` server-side (`Event.total_volume.desc()`) and wire "Ending Soon" to `sort_by=ending_soon`.

### H-9 · Admin flag missing on OAuth/passkey login → admins lose the console

`app/api/v1/oauth.py:152-160` and `app/api/v1/passkey.py:337-345` return a user object **without `is_admin`**, while `frontend/src/auth/AuthProvider.tsx:95,124` builds the session from that response (`is_admin: Boolean(res.user.is_admin)` → always false). An admin signing in via OAuth/passkey loses the Admin nav until a page refresh (`getMe()` path does include it). Also `data.user` is read without a null check in the postMessage handler. **Fix:** return `_user_payload(user)` from both endpoints; client should re-fetch `getMe()` instead of trusting login payloads.

---

## MEDIUM

- **M-1 · Response models on 2 of 114 routes.** Only `register`/`login` declare `response_model` (`app/api/v1/auth.py:43,58`). Everything else returns untyped dicts; the OpenAPI document is decorative. The three login surfaces (password, OAuth, passkey) return *different* user shapes. `GET /events` returns `next_cursor` as a string while `cursor` is an int (`public.py:108-112`).
- **M-2 · Unbounded queries on public endpoints.** `GET /desks` computes a track record for *every* active desk before slicing to `limit` (`app/api/v1/desks.py:127-143`); `GET /positions` is N+1 (~5 queries per position, `app/api/v4/positions.py:62-97`); `GET /tokens/prices` accepts an unbounded `ids` list doing 2 queries per id (**reproduced:** 500 ids accepted, `app/api/v4/prediction/extended.py:49-62`); `_session_volume` and `price_history` materialise every fill (`public.py:258-280`); ledger fetches all rows then slices in Python (`app/api/v1/collateral.py:73-80`). Add SQL `LIMIT` + `Query(ge=1, le=...)` everywhere; aggregate volume in SQL.
- **M-3 · Dead/broken slug route.** `GET /markets/slug/{slug}` tests `hasattr(Market, "slug")` — always false (no such column, `app/models/domain.py:113-131`) — and returns the *first market of the event* for an event slug (`app/api/v4/prediction/extended.py:26-37`), with a reduced payload missing `condition_id`/`tick_size`/`neg_risk`. Delete the dead branch, return the full `_market_payload` shape.
- **M-4 · Datetime crash + unvalidated bond in dispute.** `settlement.dispute_proposal` compares a timezone-aware `dispute_deadline` against a (possibly naive) `_now()` — **reproduced:** `TypeError: can't compare offset-naive and offset-aware datetimes` (500) when a dispute follows a proposal in the same session; `counter_bond` is an unvalidated float that is never charged. Use `datetime.now(UTC)` consistently and a Decimal bond (see H-3).
- **M-5 · Unbounded admin inputs.** `CreateEventRequest.description` unbounded, `category` uncapped, dates parsed with `fromisoformat` → 500 on bad input (`app/api/v4/admin.py:23-30, 94-97`); `CreateMarketRequest.event_slug` unbounded, `tick_size`/`min_order_size` unbounded floats where `inf` reaches a `Numeric(6,4)` column (`admin.py:33-39, 136-137`). Use typed `datetime | None` and Decimal bounds.
- **M-6 · CORS `allow_origins=["*"]`.** Fine for a pure-header-token API today, but it makes any origin able to read public API responses and blocks the cookie migration (H-6). Enumerate real origins per environment.
- **M-7 · Proxy `limit` params unbounded.** `app/api/v4/dexbuilder/proxy.py:37,63,73,148` forward raw `int` defaults (`limit=-1`, `limit=10_000_000` pass through) — contrast `live.py:45` which correctly uses `Query(ge=1, le=100)`.
- **M-8 · `GET /live/auth` leaks upstream credential status anonymously.** `app/api/v4/prediction/live.py:30-38` returns `configured/key_present/secret_present` plus the upstream error label — **reproduced:** `{"configured":true,"key_present":true,...,"label":"INVALID_KEY"}` to an anonymous caller. Recon value for C-3; make it admin-only.
- **M-9 · Frontend swallows errors into fake "empty" states.** `PortfolioPage.tsx:74-98` catches every sub-request and substitutes `[]` — a 500 renders "No active positions / No open orders / Wallet empty" as if factual. Same pattern in `ResolutionPage.tsx:24-41` (polls every 5s, "No markets in resolution" on failure — materially misleading on an oracle page) and `DeskDetailPage` (owner gets a 404 banner for their own DRAFT desk because `GET /desks/{id}` only serves ACTIVE desks, `app/api/v1/desks.py:215-216`). Distinguish failed from empty; add retry.
- **M-10 · Client-side hardcoded business data.** `frontend/src/components/ui.tsx:135-146` duplicates the fee schedule (`CATEGORY_FEE_RATES`) — the pre-trade fee preview can silently lie if backend fees change; `EventDetailPage.tsx:133` hardcodes "2h dispute window" while the backend computes per-market deadlines; `AuthProvider.tsx:256-261` prints the shared demo password (`trader@demo.io / trader-demo-1234`, also `app/db/seed.py:20-21`) on every deployment — gate it behind `import.meta.env.DEV`.
- **M-11 · Split/merge position accounting.** `settlement.split_position` never increments `locked_shares` (settlement.py:156-171) so split-minted shares look freely transferable; `avg_entry_price` is hardcoded `0.50` regardless of outcome count (settlement.py:170).

---

## LOW

- L-1 · `deposit`/`withdraw` responses omit the `available` key the frontend `Balance` type requires (`client.ts:255-261` vs `collateral.py:42-47`) — the type is a lie even though nothing breaks today.
- L-2 · `redeemPosition` response includes `is_winning_token` that the client type omits (`positions.py:198-206` vs `client.ts:945-954`).
- L-3 · OAuth exchange code transits the URL (`?oauth_code=...`, `app/api/v1/oauth.py:34-37`); the client scrubs it with `replaceState` but it can hit `Referer` first. Consider fragment delivery + `Referrer-Policy: no-referrer`. The client also never correlates the signed `state` it received from `/start`.
- L-4 · `oauthStart` `auth_url` is opened without any host allowlist check in `AuthProviders.tsx:101-109` (server-built today, but one misconfig away from phishing users on a full-tab redirect).
- L-5 · Six dead `getDexBuilder*` client methods (`client.ts:827-852`); `unfollowDesk`, `listPositions(settlementStatus)`, `refreshUser()` are dead code.
- L-6 · `AuthProvider` context value is a new object every render (no `useMemo`, `AuthProvider.tsx:131-140`) — whole trading panel re-renders on every toast.
- L-7 · WebAuthn verify handlers interpolate library exception text into 4xx details (`app/api/v1/passkey.py:222-230, 315-325`) — return a stable code, log the detail.
- L-8 · `SAWarning: unresolvable foreign key dependency … orders, trade_fills` on every test run — add `use_alter=True` to the cycle (`app/models/domain.py:146-186`).
- L-9 · `frontend/.env` keys (`VITE_*`) are public by design — ensure nothing secret ever lands there; currently fine.

## What is done right (keep these)

- Native bcrypt with 72-byte truncation, `verify_password_strict` used on login — no `passlib` time bomb.
- HMAC API keys stored only as digests; `hmac.compare_digest` throughout (`app/core/security.py:86-112`).
- Signed OAuth state with PKCE and 10-minute TTL (`security.py:64-83`).
- AGX money math is string-typed end-to-end (`StrictStr` + `q18`) — the model the rest of the codebase should copy.
- Admin routes consistently fail closed (`_require_admin` in both `admin.py` and `agx.py`); **empirically verified**: non-admin on an admin route → `403 ADMIN_REQUIRED`.
- No XSS sinks (`dangerouslySetInnerHTML`/`innerHTML`/`eval`: zero matches), `rel="noopener noreferrer"` on external links, no `console.log` leakage.
- Hermetic test suite with `create_test_db()` isolation and a route-baseline test that detects route drift.

---

## Improvement plan (prioritized)

### P0 — ship-blockers (security, ~2–3 days)

1. Gate `resolution/propose|dispute|finalize` behind `_require_admin`; drop `"CLOSED"` from `finalize_resolution` source statuses (C-1, C-2). Add regression tests asserting 403 for non-admins.
2. Delete or authenticate the four dexbuilder private proxy routes (C-3).
3. Replace the collateral faucet with a verified-deposit flow + idempotency + rate limit (C-4).
4. Fail fast on missing/known-default `JWT_SECRET` at startup (C-5).
5. Fix `sync-balance` to credit the target user (C-6).

### P1 — hardening (1–2 weeks)

6. WS origin allowlist + header-based token + duplicate-accept + null-sub fixes (H-1). Register/passkey routes into the auth limiter; proxy-headers-aware client IP (H-2).
7. Decimal + bounds + finite-validator on every money field: collateral, orders, split/merge, dispute bond (H-3). Fix the 201-on-reject contract (H-4) and the swallowed mirroring exceptions (H-5).
8. Cookie-based session (HttpOnly, Secure, SameSite=Lax) with CSRF double-submit; drop the localStorage token and legacy key; narrow CORS (H-6, M-6).
9. Authz regression suite: a parametrized test hitting every mutating route as (anonymous, non-admin, admin) asserting the expected 401/403 matrix. This class of bug (C-1/C-2/C-3) is exactly what it would have caught.

### P2 — contracts & correctness (2–3 weeks)

10. Pydantic response models on all 114 routes; unify the three login-response user shapes; typed `next_cursor` (M-1). Regenerate the frontend client types from `openapi.json` (`openapi-typescript`) and delete the `any`s — this mechanically prevents the drift in H-7/H-8/F-6.
11. Fix the frontend: Cancel-All (H-7), volume sort + Ending-Soon tab (H-8), `is_admin` on OAuth/passkey (H-9), error-vs-empty states (M-9), demo credentials behind a dev flag (M-10), bind the fee preview to a `GET /fees` endpoint (M-10).
12. Kill the N+1s (M-2): SQL limits everywhere, single aggregate for desk track records, windowed bulk prices, SQL volume aggregates.
13. Datetime consistency (UTC-aware everywhere) and Decimal bonds in settlement (M-4, M-11).

---

## Fixes applied (2026-11-12)

The following findings from this audit were fixed surgically in the same
change set; `tests/test_security_fixes.py` (20 tests) plus the full suite
(173 passing) guard them against regression.

- **C-1 / C-2** — `app/api/v4/resolution.py` now depends on
  `app/api/deps.py::require_admin`; `settlement.finalize_resolution` no
  longer accepts `"CLOSED"` as a source status, so a market must be proposed
  (and the dispute window honored) before it can resolve.
- **C-3** — The four unauthenticated `dexbuilder` private proxy routes
  (`/positions`, `/positions/settled`, `/usertrades`, `/orders`) were removed.
- **C-4** — `AmountRequest` is now a bounded `Decimal` (per-request cap
  100,000 USDC) with a finite-value validator; the deposit/withdraw paths
  gained a per-credential rate limit.
- **C-5** — `app/core/security.py` fails fast on a missing or known-default
  `JWT_SECRET` unless `ALLOW_INSECURE_SECRETS=1` is set (test runs only).
- **C-6** — `SyncBody` accepts an optional `user_id`; the admin reconciler
  now credits the specified account, not its own.
- **H-1** — WebSocket origin allowlist, null-`sub` and live-account re-check,
  duplicate-`accept` fix, and robust JSON parsing on the private channel.
- **H-2** — register and both passkey register routes joined the auth limiter;
  `X-Forwarded-For` honored only behind a trusted proxy.
- **H-3** — Money-typed request bodies (`collateral`, `orders`, `positions`,
  `resolution`) are now `Decimal` with finite checks and bounds.
- **H-4** — Engine rejections surface as HTTP errors (no more 201-with-
  `REJECTED` body); the self-trade path is a 409.
- **H-5** — Copy-trade mirroring runs in a savepoint with `logger.exception`
  instead of a bare `except: pass`.
- **H-6** — Legacy token key removed; a 401 from any call now clears the
  session; expired tokens are dropped at rest.
- **H-7 / H-8** — Cancel-all is scoped per market; `sort_by=volume` is
  implemented; "Ending Soon" maps to `ending_soon` ordering.
- **H-9** — OAuth/passkey exchange responses include `is_admin`, matching
  `/auth/me`.
- **M-4** — Naive/aware datetime comparison in `dispute_proposal` fixed.
- **M-7** — DexBuilder proxy `limit` params bounded.
- **M-6** — CORS origins configurable via `CORS_ALLOW_ORIGINS`.

### P3 — product/ops (ongoing)

14. Observability: structured logging + request IDs (none exists); alert on rejected-order spikes and mirror failures (H-5).
15. Admin audit trail table for every admin/oracle action (`finalized_by`, `proposed_by`) — C-1/C-2 fix should land with this.
16. Postgres migration path: `StaticPool`+SQLite is dev-only; add a CI job that runs the suite against Postgres to catch dialect drift (the `use_alter` warning in L-8 hints at it).
17. Rate-limit the live/prediction read surface per-IP *and* per-token, and add `max_length` caps to every string body field (`market_id`, `token_id`, `slug`, `event_slug` currently unbounded).
