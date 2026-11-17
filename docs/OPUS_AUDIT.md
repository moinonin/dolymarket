# Local / Community Markets Flow Audit (`OPUS_AUDIT`)

Audit done, no repo files changed. It has 5 High and 11 Medium findings plus some Low/UX items, each with code references or probe output. The most serious ones:

- **Rigging by the creator:** the `static:<n>` oracle feed in [oracle.py](app/services/oracle.py#L99-L109) returns any number, and community creation accepts it. A creator can set a feed that makes their own position win, and the worker auto-finalizes it after 2h.
- **Disputes:** [resolution.py](app/api/v4/resolution.py#L92) restricts disputes to admins, so affected traders can't contest. The Resolution page still shows them a dispute button, which returns 403.
- **Concurrency:** nothing in [positions.py](app/api/v4/positions.py#L176-L198), [amm.py](app/services/amm.py) or [settlement.py](app/services/settlement.py) locks rows. Redeem can double-claim and split can overspend on Postgres. SQLite hides this, and I only read the code; I did not test it under Postgres.
- **LP deposit re-pricing:** a second deposit changes `b` on a live pool. In my probe the YES price moved from 0.7388 to 0.5876.
- **Stuck funds:** LP money in an `UNFUNDED` market (under the $10 threshold) can't be refunded, because the worker only closes `ACTIVE` markets.
- **Input validation:** an invalid `end_date` returns HTTP 500, and a past `end_date` is accepted. A malformed `oracle_feed` is stored and retried every 30s, and `Violence & Crime` passes the category blocklist.
- **No UI for the community flow:** `createCommunityMarket` and `fundCommunityMarket` exist in `client.ts` but no page calls them, and there are no AMM or LP client methods.

Verified: `pytest tests/test_community_markets.py tests/test_amm.py tests/test_resolution_worker.py` gives 6 passed. The probes ran in an in-memory DB. I did not review CLOB matching internals or `EventDetailPage`, and I did not run the frontend.

Decision for you: should dispute be open to traders with real bond escrow, or stay admin-only with the button hidden for non-admins?

Suggested order is H1 (oracle rigging) first, then the locking and LP issues.

---

## Implementation Review & Verification Status (2026-11-17 — All Fixed)

**Final verification runs:**
- `pytest -q -p no:cacheprovider`: **214 passed, 2 warnings in 60.79s** (0 failed).
- `cd frontend && npm run build`: **exit 0** (`✓ built in 2.02s`).
- `ruff check --select F821 app/ tests/`: **All checks passed!**; `ruff check app/services/resolution_worker.py tests/test_resolution_worker.py`: **0 errors remaining**.
- Runtime probe `review_probe_h4.py`: `before 2nd deposit: pool.q_yes=150.0000`, `after 2nd deposit: pool.q_yes=150.0000`, `LP equity understated by 0.0000 USDC`.
- Runtime probe `review_probe_m8_m9.py`: M8 `CANCELLED` (`locked_balance` `4.0000` → `0.0000`), M9 sibling sync `CLOSED` → `RESOLVED`.

### Final Status Matrix

| ID | Finding | Status | Implementation |
|---|---|---|---|
| H1 | Creator `static:` oracle rigging | **DONE** | Blocked on community & prod (`allow_static=False`); malformed/incomplete rejected (`422`). |
| H2 | Redeem double-claim race | **DONE** | `.with_for_update()` on `Position` and `CollateralAccount` (`positions.py`). |
| H3 | AMM & split/merge missing row locks | **DONE** | Canonical lock order `Market -> AmmPool -> AmmLpPosition/Position -> CollateralAccount`; `approval_account` uses `get_or_create_account(..., for_update=True)`. |
| H4 | Second LP deposit re-prices / breaks liability | **DONE** | Keeps `b` fixed once AMM trades exist (`q_yes != 0 or q_no != 0`); price invariant AND `pool.q_yes == held shares` (`0.0000` equity drift). |
| H5 | Stuck LP funds in `UNFUNDED` markets | **DONE** | Worker expires past `end_date` (`EXPIRED`) and refunds partial LP deposits pro rata. |
| M1 | Invalid `end_date` / duplicate slug HTTP 500 | **DONE** | ISO validators on `community.py` & `admin.py` (`422`); slug `ValueError` → `409`. |
| M2 | Past `end_date` accepted | **DONE** | Requires `end_date > now + 5m` on community creation. |
| M3 | Malformed oracle stored & 30s retry spam | **DONE** | Format/threshold validated (`422`); worker adds exponential backoff (`30s`–`1800s`); `/run-tick` returns `expired`. |
| M4 | Oracle observes spot at tick time, not `end_date` | **DONE** | Fetches Gate 1m historical close candle at `end_date` when `>60s` past close (refuses >1h stale spot fallback). |
| M5 | Dispute admin-only vs UI mismatch | **DONE** | Validates `dispute_proposal` first, locks `100 AGX` via `agx.stake_dispute`, updates `ResolutionPage.tsx` (`100 AGX`), logs `AgxError` on finalize, `test_security_fixes.py` updated & passing. |
| M6 | Category blocklist exact match only | **DONE** | `contains_prohibited_content` checks substrings across category, title, question, criteria. |
| M7 | 3+ outcome community markets accepted | **DONE** | Enforces exact binary (`min_length=2, max_length=2`) outcomes on `community.py`. |
| M8 | Resting CLOB orders not cancelled on close | **DONE** | `cancel_market_orders` on close/auto-close (`CANCELLED`, locks released). |
| M9 | Event status ignores sibling markets | **DONE** | `sync_event_status` updates parent `Event` only after sibling markets transition. |
| M10 | Funding endpoints skip tier check | **DONE** | Both `community.py` `/fund` and `amm.py` `/amm/{id}/deposit` enforce `COMMUNITY` tier (or admin). |
| M11 | Worker cross-process lock / uniqueness | **DONE** | `.with_for_update()` on `Market` + `uq_active_dispute_per_market` partial unique index on `oracle_disputes`. |
| Low/UX | Frontend community & AMM/LP flow | **DONE** | `EventDetailPage.tsx` links directly to `AMM & LP Pool →` (`#market/<id>`); `AdminPage.tsx` lists `UNFUNDED`; `'EXPIRED'` in `client.ts`; `amm.py` logs AGX fee errors. |
