# Feature: Pro Desks — non-custodial copy trading for Dolymarket

## Change type and operating rules

This is a brownfield change to an existing repository, not a new project. Read
the files listed under Context and follow the conventions already in them
before writing anything. Extend the existing modules in place:

- append the new models to `app/models/domain.py` beside the models already
  there;
- add the new routers under `app/api/v1/` as siblings of `auth.py` and
  `collateral.py`, and mount them in `app/main.py` beside the existing
  `include_router` calls;
- extend the existing order endpoint in `app/api/v4/orders.py` and the existing
  admin router in `app/api/v4/admin.py` rather than adding parallel routes;
- add the new views under `frontend/src/pages/` and wire them into the existing
  hash router in `frontend/src/App.tsx`.

Do not scaffold a new project, do not regenerate an existing file from the top,
do not declare a second `Base`, a second `User` model, a second `FastAPI`
instance, or a duplicate route path, and do not replace working code with a
rewrite. The endpoint contract captured in `.githeri/baseline.json` is the
pre-change baseline: every entry in it must still resolve after this change,
and `tests/test_route_baseline.py` enforces that. Adding endpoints is expected;
removing or renaming one is not.

## Context

Dolymarket is a prediction market platform in this repository. The relevant
existing pieces are:

- `app/api/v1/` — auth (email/password, OAuth providers, WebAuthn passkeys),
  collateral deposits/withdrawals/ledger.
- `app/api/v4/orders.py` — authenticated order submission at
  `POST /api/v4/prediction/orders`, with `X-Idempotency-Key` replay protection
  and depth broadcasts.
- `app/api/v4/public.py` — public market discovery (events, markets, tickers,
  order book depth).
- `app/api/v4/positions.py` — the caller's positions, fills and redemption.
- `app/engine/clob.py` — `MatchingEngine` (price-time priority) and
  `OrderBook`; `app/engine/book.py` — `InMemoryOrderBook`;
  `app/engine/fill_queue.py` — write-behind fill persistence.
- `app/services/collateral.py` — the only path that moves money:
  `get_or_create_account(..., for_update=True)` (row-level lock via
  `with_for_update`), `lock_for_buy`, `release_lock`, `charge_fee`,
  `credit_payout`, and the collateral ledger entries `DEPOSIT`, `WITHDRAWAL`,
  `LOCK`, `RELEASE`, `FEE`, `PAYOUT`.
- `app/models/domain.py` — `User`, `CollateralAccount`, `Market`,
  `OutcomeToken`, `Order`, `TradeFill`, `Position`.
- `frontend/src/` — Vite + React + TypeScript + Tailwind v4 + lucide-react,
  typed client in `frontend/src/api/client.ts`, hash router in
  `frontend/src/App.tsx`, Portfolio tabs in
  `frontend/src/pages/PortfolioPage.tsx`.

All money columns are `Numeric(18,4)` (`Numeric(6,4)` for prices) and all
service code uses `Decimal`.

## Goal

Add a copy-trading product called **Pro Desks**. A *desk* is a public track
record owned by exactly one user (the *operator*). A desk trades only with the
operator's own collateral, using normal orders that carry a `desk_id` tag. A
*follower* opts in to a desk with a copy ratio; each desk fill is then mirrored
proportionally into the follower's **own** collateral account, using the
follower's own balance. Copying is non-custodial: no pooled balance, no vault
share, no net asset value, no redemption, and no fee tied to trading results.

## Explicit non-goals

- No pooled or commingled capital. No platform-held balance for copying.
- No vault share token, no share accounting, no net-asset-value marking, no
  entry or exit spread.
- No redemption endpoint and no withdrawal on a follower's behalf.
- No result-based fee, no carried interest, no high-water mark, no rebate,
  bonus, or prize conditioned on trading results.
- No leverage, no margin, no borrowing.
- No copying of the operator's personal (untagged) orders.
- No more than one desk per user account.
- No liquidity-provision or market-making desk. No quoting obligations.
- No deletion of copy history and no operator-supplied track-record numbers.

## Actors, roles and ownership boundaries

Four roles:

- **Visitor** — unauthenticated. May read the public desk list and the public
  profile and track record of an `ACTIVE` desk. Must receive HTTP 401 on every
  mutating route.
- **Follower** — any authenticated user who follows a desk. May create, read,
  update and delete only their own follow record, and may read only their own
  copy-job history.
- **Operator** — the authenticated owner of a desk. May read and modify only
  their own desk, may read only their own desk's follower list and copy-job
  summary, and may tag their own orders with their own `desk_id`.
- **Admin** — an authenticated user with `is_admin = True` on the `users` row.
  The repository has no admin role today, so add the boolean flag
  (`User.is_admin`, default `False`) and require it on the desk review routes.
  An authenticated caller without the flag must receive HTTP 403
  `ADMIN_REQUIRED`; an anonymous caller must receive HTTP 401. The desk review
  routes live under the existing admin router prefix
  (`app/api/v4/admin.py`, prefix `/api/v4/prediction/admin`).

Ownership rules (mandatory):

- A user must not read or modify another user's desk record, follow record, or
  copy-job history. Such a request must be rejected with HTTP 403 and must not
  disclose the target row. A request for an id that does not exist must return
  HTTP 404.
- Only the desk owner may submit an order tagged with that `desk_id`. Any other
  authenticated user supplying that `desk_id` must be rejected with HTTP 403
  `DESK_ORDER_FORBIDDEN`.
- An operator must not follow their own desk; the request must be rejected with
  HTTP 409 `DESK_SELF_FOLLOW`.
- A follower must never be able to read the desk operator's collateral balance,
  positions or ledger, and an operator must never be able to read a follower's
  collateral balance, positions or ledger. Follower lists expose only
  `follower_user_id`, `copy_ratio` and `status`.
- The public desk list and public desk profile must never expose
  `owner_user_id`'s email, balances, or any follower's private data.

## Domain model

New SQLAlchemy models in `app/models/domain.py`, plus one column on `User`:

- `User` gains `is_admin` Boolean, default `False`, nullable false, used only
  as the authorization flag for desk review routes.

- `Desk`
  - `id` String(36) PK, `owner_user_id` FK `users.id` (unique — one desk per
    owner), `name` String(80), `slug` String(96) unique, `description`
    Text nullable, `status` String(20), `review_note` Text nullable,
    `created_at`, `activated_at` nullable, `suspended_at` nullable,
    `archived_at` nullable.
- `DeskFollower`
  - `id` String(36) PK, `desk_id` FK, `follower_user_id` FK,
    `copy_ratio` `Numeric(5,4)`, `per_market_cap_usdc` `Numeric(18,4)`,
    `max_per_market_pct` `Numeric(5,2)`, `max_total_pct` `Numeric(5,2)`,
    `status` String(16) (`ACTIVE` or `PAUSED`), `created_at`,
    `updated_at`. Unique constraint on `(desk_id, follower_user_id)`.
- `DeskPosition`
  - `id` String(36) PK, `desk_id` FK, `market_id` FK, `token_id` String(100),
    `outcome_index` Integer, `shares` `Numeric(18,4)`, `avg_entry_price`
    `Numeric(6,4)`, `realized_pnl_usdc` `Numeric(18,4)`, `settled_at`
    nullable, `updated_at`. Unique constraint on `(desk_id, token_id)`.
- `CopyJob`
  - `id` String(36) PK, `desk_id` FK, `follower_user_id` FK,
    `source_fill_id` FK `trade_fills.id`, `status` String(32),
    `copy_ratio` `Numeric(5,4)`, `requested_shares` `Numeric(18,4)`,
    `requested_cost_usdc` `Numeric(18,4)`, `filled_shares` `Numeric(18,4)`,
    `filled_cost_usdc` `Numeric(18,4)`, `limit_breached` Boolean,
    `error_code` String(64) nullable, `created_at`, `updated_at`.
    Unique constraint on `(follower_user_id, source_fill_id)`.
- `Order` gains two nullable columns: `desk_id` FK `desks.id` and
  `copy_source_fill_id` FK `trade_fills.id`.

Every money, price, share, ratio, percentage and cap value must be stored and
computed with fixed-point Decimal types (`Numeric(18,4)`, `Numeric(6,4)`,
`Numeric(5,4)`, `Numeric(5,2)`). Binary floating point arithmetic must not be
used for balances, prices, fees, shares, or caps. Rounding of money and shares
must truncate toward zero at four decimal places.

## Desk lifecycle state machine

Statuses: `DRAFT`, `PENDING_REVIEW`, `ACTIVE`, `SUSPENDED`, `REJECTED`,
`ARCHIVED`.

Allowed transitions and their guards:

| From | Action | To | Guard |
|---|---|---|---|
| — | create | `DRAFT` | authenticated user with no existing desk, else HTTP 409 `DESK_ALREADY_EXISTS` |
| `DRAFT`, `REJECTED` | submit | `PENDING_REVIEW` | track record meets the eligibility thresholds below, else HTTP 422 `DESK_TRACK_RECORD_INSUFFICIENT` |
| `PENDING_REVIEW` | admin approve | `ACTIVE` | admin caller only, else HTTP 403 |
| `PENDING_REVIEW` | admin reject | `REJECTED` | `reason` required (min length 1), else HTTP 422 |
| `ACTIVE` | admin suspend | `SUSPENDED` | admin caller only |
| `ACTIVE` | operator self-suspend | `SUSPENDED` | desk owner only |
| `SUSPENDED` | submit | `PENDING_REVIEW` | desk owner only |
| `DRAFT`, `REJECTED`, `ACTIVE`, `SUSPENDED` | archive | `ARCHIVED` | desk owner, irreversible, sets `archived_at` and sets every `DeskFollower.status` to `PAUSED` |
| any | any | — | a request that is not one of the rows above must be rejected with HTTP 409 `DESK_INVALID_TRANSITION` |

State guards (mandatory):

- While the desk status is `DRAFT`, `PENDING_REVIEW`, `REJECTED`, `SUSPENDED`
  or `ARCHIVED`, the desk must not accept a new follower (HTTP 409
  `DESK_NOT_ACTIVE`), must not accept an order tagged with the `desk_id`
  (HTTP 409 `DESK_NOT_ACTIVE`), and must not produce any copy job.
- Once the desk status is `ARCHIVED`, the transition is terminal: every later
  transition request must be rejected with HTTP 409
  `DESK_INVALID_TRANSITION`.
- When a desk is `ACTIVE`, it must hold at least one settled desk position
  before it can be re-submitted for review.
- Two suspension triggers must be evaluated by the copy engine and by a check
  on the desk's own order path:
  - `DRAWDOWN_BREAKER`: the desk's rolling 30-day realized drawdown (defined in
    the track-record section) is at or below `-DESK_DRAWDOWN_BREAKER_PCT`
    (default 20). Sets status `SUSPENDED` and `review_note=DRAWDOWN_BREAKER`.
  - `INSUFFICIENT_OPERATOR_FUNDS`: a desk-tagged order cannot lock its cost
    because the operator's available balance is insufficient. Sets status
    `SUSPENDED` and `review_note=INSUFFICIENT_OPERATOR_FUNDS`.
  A desk suspended by a trigger must not be reactivated except through the
  operator submit then admin approve path.

## Desk eligibility thresholds

A desk may transition from `DRAFT` or `REJECTED` to `PENDING_REVIEW` only when
all of the following are true, computed from stored fills and settled desk
positions and never from operator input:

- `closed_positions >= DESK_MIN_CLOSED_POSITIONS` (default 10).
- `days_active >= DESK_MIN_DAYS_ACTIVE` (default 14), where `days_active` is
  the whole number of calendar days between the desk's first desk-tagged fill
  (`created_at`) and the submit request time (UTC).
- At least one desk-tagged order exists.

Otherwise the response is HTTP 422 `DESK_TRACK_RECORD_INSUFFICIENT` with a body
listing each unmet threshold, for example
`{"detail": {"code": "DESK_TRACK_RECORD_INSUFFICIENT", "unmet": ["closed_positions"]}}`.
Profitability is disclosed on the track record but must not be a listing gate.

## Track record formulas

The track record is a deterministic function of stored data. All values are
Decimal truncated to four decimal places.

Let the desk's **source fills** be the rows of `trade_fills` whose
`maker_order_id` or `taker_order_id` belongs to an `orders` row with this
`desk_id`, and whose own order is not itself a copy order
(`copy_source_fill_id IS NULL`).

Let a desk position be **settled** when its market has
`winning_outcome_index IS NOT NULL`.

- `cost_basis_usdc = sum(settled.shares * settled.avg_entry_price)`
- `payout_usdc = sum(settled.shares * 1.0000)` over settled positions whose
  `outcome_index == market.winning_outcome_index`, otherwise `0.0000`
- `fees_paid_usdc = sum(source_fill.maker_fee + source_fill.taker_fee)` for the
  desk side of each source fill
- `realized_pnl_usdc = payout_usdc - cost_basis_usdc`
- `net_pnl_usdc = realized_pnl_usdc - fees_paid_usdc`
- `closed_positions = count(settled positions)`
- `winning_positions = count(settled positions with payout_usdc)`
- `win_rate = winning_positions / closed_positions`, and exactly `0.0000` when
  `closed_positions == 0`
- `roi_pct = (net_pnl_usdc / max(cost_basis_usdc, 0.0100)) * 100`
- `avg_win_usdc` and `avg_loss_usdc` over settled positions with positive and
  negative realized pnl respectively, `0.0000` when there is no such position
- `max_drawdown_pct`: order settled positions by `settled_at` ascending, ties
  ordered by desk position id ascending, and accumulate `realized_pnl_usdc`
  (fees excluded). With `running` the cumulative sum, `peak = max(0, running)`:
  `dd_pct = ((peak - running) / peak) * 100` when `peak > 0`, else `0`. Return
  the maximum `dd_pct`.
- `rolling_drawdown_30d_pct`: the same computation restricted to settled
  positions with `settled_at >= now - 30 days`.
- `active_follower_count` and `copied_fill_count` (copy jobs with status
  `FILLED` or `PARTIALLY_FILLED`).

Worked example that automated tests must assert exactly. Desk with two settled
positions and source-fill fees of `0.5000`:

- P1: `shares=100.0000`, `avg_entry_price=0.4000`, outcome 0 wins
  → cost `40.0000`, payout `100.0000`, realized `+60.0000`
- P2: `shares=50.0000`, `avg_entry_price=0.5500`, outcome 0 wins but P2 holds
  outcome 1 → cost `27.5000`, payout `0.0000`, realized `-27.5000`

Results: `cost_basis_usdc=67.5000`, `payout_usdc=100.0000`,
`realized_pnl_usdc=32.5000`, `net_pnl_usdc=32.0000`, `closed_positions=2`,
`winning_positions=1`, `win_rate=0.5000`,
`roi_pct=47.4074`, `avg_win_usdc=60.0000`, `avg_loss_usdc=-27.5000`,
`max_drawdown_pct=45.8333`.

## Copy rules and sizing

A copy job is created for each `(active follower, desk source fill)` pair. The
copy order is placed in the follower's own account, on the same market and
token, on the same side as the source fill, as a `LIMIT` order at the source
fill price with `time_in_force="IOC"`.

Copy job statuses: `PENDING`, `FILLED`, `PARTIALLY_FILLED`,
`SKIPPED_INSUFFICIENT_FUNDS`, `SKIPPED_STALE`, `SKIPPED_NO_LIQUIDITY`,
`SKIPPED_MARKET_CLOSED`, `SKIPPED_LIMIT_BREACHED`, `FAILED`.

Evaluation order, first matching rule wins:

1. Follower status must be `ACTIVE` and the desk status `ACTIVE`. Otherwise the
   fill must be skipped and no copy job may be created for a paused follower.
2. Market status must be `ACTIVE`. Otherwise `SKIPPED_MARKET_CLOSED`.
3. The reference price is the current best ask for a `BUY` source fill and the
   current best bid for a `SELL` source fill. If that side of the book is
   empty, the job status is `SKIPPED_NO_LIQUIDITY`.
4. Staleness guard: with `bps = abs(source_price - reference_price) /
   reference_price * 10000`, if `bps > DESK_STALENESS_BPS` (default 200) the
   job status is `SKIPPED_STALE`.
5. Compute `target_shares` with the sizing formula below. If
   `target_shares < market.min_order_size`, the job status is
   `SKIPPED_INSUFFICIENT_FUNDS` when
   `available_usdc < market.min_order_size * price`, otherwise
   `SKIPPED_LIMIT_BREACHED`.
6. Otherwise place the copy order. If the order fills completely the status is
   `FILLED`; if it fills partly the status is `PARTIALLY_FILLED`; if it fills
   nothing the status is `SKIPPED_NO_LIQUIDITY`. Any other rejection from the
   matching engine sets `FAILED` and records `error_code`.

Sizing formula (all Decimal, truncated to four decimal places):

```
gross_cost_usdc      = leader_shares * copy_ratio
follower_equity_usdc = account.balance + account.locked_balance
per_market_budget    = min(per_market_cap_usdc,
                           follower_equity_usdc * max_per_market_pct / 100)
total_budget_usdc    = follower_equity_usdc * max_total_pct / 100
market_exposure_usdc = sum over the follower's open copy orders in this market
                       of (remaining_shares * price)
                     + sum over the follower's open copy positions in this
                       market of (shares * avg_entry_price)
total_exposure_usdc  = the same sums across all markets
remaining_market     = max(0, per_market_budget - market_exposure_usdc)
remaining_total      = max(0, total_budget_usdc - total_exposure_usdc)
available_usdc       = max(0, account.balance - account.locked_balance)
budget_usdc          = min(gross_cost_usdc, remaining_market, remaining_total,
                           available_usdc)
target_shares        = budget_usdc / price
limit_breached       = budget_usdc < gross_cost_usdc
```

Worked example that automated tests must assert exactly:

- `leader_shares=200.0000`, `copy_ratio=0.2500`, `price=0.4000`
  → `gross_cost_usdc=50.0000`
- `account.balance=180.0000`, `account.locked_balance=20.0000`
  → `follower_equity_usdc=200.0000`, `available_usdc=160.0000`
- `per_market_cap_usdc=50.0000`, `max_per_market_pct=20.00`
  → `per_market_budget=40.0000`
- `max_total_pct=25.00` → `total_budget_usdc=50.0000`
- no existing exposure → `remaining_market=40.0000`, `remaining_total=50.0000`
- `budget_usdc=40.0000`, `target_shares=100.0000`, `limit_breached=true`

Mirroring invariants (mandatory):

- At most one copy job may exist per `(follower_user_id, source_fill_id)`. The
  database unique constraint must enforce this, and two concurrent copy-engine
  runs must not create two copy orders for the same source fill.
- A copy order must be a normal `orders` row owned by the follower with
  `copy_source_fill_id` set to the source fill id. It must appear in the
  follower's own order list, positions and ledger, and the follower must be
  able to cancel it.
- The copy order's market and token must equal the source fill's market and
  token, and its side must equal the source fill's side. A `BUY` copy order
  must lock collateral with `lock_for_buy`; a `SELL` copy order must lock the
  corresponding shares with the existing position path.
- The copy engine must copy the desk side of a source fill exactly once and
  must never copy the counterparty's side.
- The copy engine must not copy a fill whose own order is already a copy order,
  so copies cannot compound recursively.
- A copy job must never credit a follower balance outside the existing
  collateral paths.

## Money, ledger and concurrency rules

- Every copy order must use the existing collateral service. Before matching it
  must take a row-level lock on the follower's collateral account via
  `get_or_create_account(session, follower_user_id, for_update=True)` (which
  issues `with_for_update`) and then verify and reserve with `lock_for_buy`.
  A request must be rejected, and no order may be sent to the matching engine,
  when the available balance is insufficient.
- The locked increment must be released with `release_lock` for the unfilled
  remainder of an `IOC` copy order, and fees must be charged through
  `charge_fee`. Each lock, release and fee must write the standard collateral
  ledger entry.
- `locked_balance` must never exceed `balance`, and `balance` must never become
  negative. `available_usdc = balance - locked_balance` must never be treated
  as a spendable amount without holding the row-level lock.
- Money conservation: for a follower, `balance + locked_balance` changes only
  by deposits, withdrawals, fees, payouts, and settlement of that follower's
  own positions. A copy job must not change it by any other amount.
- The platform must hold no pooled balance for copy activity, must expose no
  share or unit for a desk, and must expose no redemption route for copy
  activity.

## Anti front-running rules

- While a desk is `ACTIVE` and holds a non-zero `DeskPosition` in a market, the
  operator must not submit an untagged (personal) order in that market. The API
  must reject the request with HTTP 409 `DESK_MARKET_CONFLICT`.
- A desk-tagged order in that market is allowed, because it is the desk's own
  trading. While the desk is not `ACTIVE`, a desk-tagged order must be rejected
  with HTTP 409 `DESK_NOT_ACTIVE`.
- Only the desk owner may supply a `desk_id` on an order. Another authenticated
  user doing so must be rejected with HTTP 403 `DESK_ORDER_FORBIDDEN`. An
  anonymous caller must receive HTTP 401.
- A `desk_id` that does not exist must be rejected with HTTP 404.
- Every desk source fill must update `DeskPosition` for the desk in the same
  transaction as the fill, so the conflict check reads stored state rather than
  a request value.

## API surface

Public, no authentication:

- `GET /api/v1/desks` — list `ACTIVE` desks with track-record fields.
  Query `sort` in `{roi_pct, net_pnl_usdc, active_follower_count, created_at}`,
  default `roi_pct`; `limit` default 20, maximum 100. An unknown `sort` value
  must return HTTP 422. Fields: `id`, `name`, `slug`, `description`,
  `active_follower_count`, `copied_fill_count`, `closed_positions`, `win_rate`,
  `roi_pct`, `net_pnl_usdc`, `max_drawdown_pct`, `created_at`.
- `GET /api/v1/desks/{desk_id}` — public profile plus the full track record.
  An `ACTIVE` desk is public; a desk whose status is not `ACTIVE` must return
  HTTP 404 to an anonymous caller; an unknown id must return HTTP 404.
- `GET /api/v1/desks/{desk_id}/track-record` — the track-record object plus the
  realized equity curve (settled positions ordered by `settled_at`). Same
  visibility rule and HTTP 404 behavior.

Authenticated:

- `POST /api/v1/desks` — create the caller's desk. Body `name` (1..80),
  `slug` (1..96, `^[a-z0-9-]+$`), `description` optional. Returns 201 with
  status `DRAFT`. Errors: HTTP 401 anonymous, HTTP 409 `DESK_ALREADY_EXISTS`
  when the caller already owns a desk, HTTP 422 malformed body.
- `GET /api/v1/desks/mine` — the caller's own desk and track record; HTTP 404
  when the caller owns no desk.
- `PUT /api/v1/desks/{desk_id}` — update `name` and `description` while the
  desk status is `DRAFT` or `REJECTED`; otherwise HTTP 409
  `DESK_NOT_EDITABLE`. Errors: HTTP 403 for another user's desk, HTTP 404
  unknown id.
- `POST /api/v1/desks/{desk_id}/submit` — transition to `PENDING_REVIEW` from
  `DRAFT` or `REJECTED`. Errors: HTTP 403 non-owner, HTTP 404 unknown id,
  HTTP 409 `DESK_INVALID_TRANSITION`, HTTP 422 `DESK_TRACK_RECORD_INSUFFICIENT`.
- `POST /api/v1/desks/{desk_id}/suspend` — operator self-suspend from `ACTIVE`.
  HTTP 409 for any other source status.
- `POST /api/v1/desks/{desk_id}/archive` — irreversible; sets `ARCHIVED`.
  HTTP 409 when already `ARCHIVED`.
- `GET /api/v1/desks/{desk_id}/followers` — owner only; HTTP 403 for a
  follower or a third party, HTTP 404 unknown id.
- `GET /api/v1/desks/{desk_id}/copy-jobs` — owner only; aggregate counts per
  status for that desk plus the most recent 50 jobs.

Admin review, added to the existing `app/api/v4/admin.py` router and guarded by
`User.is_admin`:

- `POST /api/v4/prediction/admin/desks/{desk_id}/approve` — `PENDING_REVIEW` to
  `ACTIVE`; HTTP 409 `DESK_INVALID_TRANSITION` otherwise, HTTP 403
  `ADMIN_REQUIRED` for an authenticated non-admin, HTTP 401 anonymous.
- `POST /api/v4/prediction/admin/desks/{desk_id}/reject` — body `reason`
  (1..500); HTTP 422 when `reason` is missing, HTTP 403 `ADMIN_REQUIRED`
  otherwise.
- `POST /api/v4/prediction/admin/desks/{desk_id}/suspend` — any status except
  `ARCHIVED` to `SUSPENDED`; HTTP 403 `ADMIN_REQUIRED` otherwise.

Follower routes:

- `POST /api/v1/desks/{desk_id}/follow` — body `copy_ratio` optional,
  `per_market_cap_usdc` optional, `max_per_market_pct` optional,
  `max_total_pct` optional. Returns 201. Errors: HTTP 401 anonymous,
  HTTP 404 unknown id, HTTP 409 `DESK_NOT_ACTIVE`, HTTP 409
  `DESK_ALREADY_FOLLOWED`, HTTP 409 `DESK_SELF_FOLLOW`, HTTP 422
  `COPY_RATIO_OUT_OF_RANGE`, HTTP 422 `CAP_OUT_OF_RANGE`, HTTP 422
  `INSUFFICIENT_BALANCE` when `available_usdc` is below a minimum first-copy
  cost of `10.0000`.
- `PUT /api/v1/desks/{desk_id}/follow` — update `copy_ratio`, the three cap
  values, or `status` in `{ACTIVE, PAUSED}`. Errors: HTTP 404
  `FOLLOW_NOT_FOUND` when the caller does not follow the desk, HTTP 422 on an
  out-of-range value.
- `DELETE /api/v1/desks/{desk_id}/follow` — unfollow, returns 204; HTTP 404
  `FOLLOW_NOT_FOUND` when not following.
- `GET /api/v1/copy-jobs` — the caller's own copy jobs, `limit` default 20
  maximum 100, `status` filter optional. HTTP 401 anonymous.

Order submission, existing route:

- `POST /api/v4/prediction/orders` accepts an optional `desk_id`. Errors:
  HTTP 403 `DESK_ORDER_FORBIDDEN`, HTTP 404 unknown `desk_id`, HTTP 409
  `DESK_NOT_ACTIVE`, HTTP 409 `DESK_MARKET_CONFLICT`. Requests without
  `desk_id` must behave exactly as today, including `X-Idempotency-Key`
  replay protection.

Range validation: `copy_ratio` in `[DESK_MIN_COPY_RATIO, DESK_MAX_COPY_RATIO]`
(default `0.0100` to `1.0000`); `per_market_cap_usdc` in `[10.0000, 1000000.0000]`;
`max_per_market_pct` in `[1.00, 100.00]`; `max_total_pct` in
`[max_per_market_pct, 100.00]`.

## Frontend requirements

- `frontend/src/pages/DesksPage.tsx` at hash route `#/desks` — public
  leaderboard read from `GET /api/v1/desks`, with sort control, loading state,
  empty state ("No desks are live yet") and an error banner with retry.
- `frontend/src/pages/DeskDetailPage.tsx` at hash route `#/desks/{id}` —
  public profile: track-record table, the realized equity curve (reuse the
  existing Lightweight Charts setup), the follower count, and the follow
  controls. Anonymous visitors see a sign-in call to action instead of the
  follow controls.
- Follow controls: copy-ratio input with the allowed range shown, the three cap
  inputs, `Follow desk`, `Pause copying`, `Unfollow`, and a link to the
  caller's copy-job history.
- Portfolio gains a `Desks` tab in
  `frontend/src/pages/PortfolioPage.tsx` — create the caller's desk, submit it
  for review, view its status and review note, view its followers and copy-job
  counts, self-suspend and archive. Plus a `Copy Jobs` view for the caller's own
  jobs with the status and skip reason for each job.
- Every data view must read from the API through `frontend/src/api/client.ts`.
  Mock data arrays must not be left in any view. Every list and table must
  handle a loading state, an empty state, and an error state.
- No component may contain a hardcoded `localhost` or `127.0.0.1` URL; use the
  typed client and `import.meta.env.VITE_API_URL` relative fallbacks.
- Keep Tailwind v4 (`@import "tailwindcss";`, `@tailwindcss/vite`) and use
  lucide-react icons.
- Every screen that shows a track-record number must show the label
  "Past results, not indicative of future results."
- Domain vocabulary in headings, buttons and labels must be desk language
  ("Live desks", "Follow desk", "Copy ratio", "Copy jobs"), not generic
  placeholder entities.

## Regulatory and disclosure constraints

- Copying must be non-custodial: the follower's own collateral account funds
  every copy order, and the platform must not hold or pool follower funds for
  copying.
- The product must expose no share, unit, net asset value, deposit-into-desk,
  or redemption route.
- The platform must charge no fee tied to a desk's trading results. A flat
  subscription fee is out of scope for this change.
- Marketing surfaces must not contain projected, target, or forward-looking
  return figures, and must not attach any bonus, rebate, referral reward, or
  prize to trading results.
- Every track-record figure must be computed from stored source fills and
  settled desk positions. Operator-supplied numbers must never be displayed.
- Copy jobs and source fills must be append-only from the operator's
  perspective: the operator must not be able to delete copy history, and a
  track-record query must not depend on a client-supplied value.
- These routes must be enabled by `COPY_TRADING_ENABLED` (default `true`). When
  it is `false`, every desk route must return HTTP 404 and the frontend must
  hide the desk navigation.

## Environment variables

Document these in `.env.example` and the README:

- `COPY_TRADING_ENABLED` (default `true`)
- `DESK_MIN_CLOSED_POSITIONS` (default `10`)
- `DESK_MIN_DAYS_ACTIVE` (default `14`)
- `DESK_MIN_COPY_RATIO` (default `0.0100`)
- `DESK_MAX_COPY_RATIO` (default `1.0000`)
- `DESK_DEFAULT_COPY_RATIO` (default `0.2500`)
- `DESK_DEFAULT_PER_MARKET_CAP_USDC` (default `50.0000`)
- `DESK_MAX_PER_MARKET_EQUITY_PCT` (default `20`)
- `DESK_MAX_TOTAL_EQUITY_PCT` (default `25`)
- `DESK_STALENESS_BPS` (default `200`)
- `DESK_DRAWDOWN_BREAKER_PCT` (default `20`)

## Automated verification

Add automated pytest integration tests that exercise the actual API routes and
the real database session, covering both allowed and rejected cases. Required
coverage, with the file that must contain it:

`tests/test_desks.py`

- Creating a desk returns 201 with status `DRAFT`; creating a second desk for
  the same owner returns 409 `DESK_ALREADY_EXISTS`.
- `PUT` by a non-owner returns 403; an unknown desk id returns 404.
- `PUT` on a desk that is not `DRAFT` or `REJECTED` returns 409
  `DESK_NOT_EDITABLE`.
- `submit` below the thresholds returns 422 `DESK_TRACK_RECORD_INSUFFICIENT`
  and lists the unmet threshold; after seeding ten settled desk positions and a
  first fill more than fourteen days old, `submit` returns 200 with
  `PENDING_REVIEW`.
- `approve` returns `ACTIVE`; approving again returns 409
  `DESK_INVALID_TRANSITION`.
- `reject` without a reason returns 422.
- Desk review authorization: an authenticated caller without `is_admin` gets
  HTTP 403 `ADMIN_REQUIRED` on approve, reject and suspend; an anonymous caller
  gets HTTP 401.
- `GET /api/v1/desks/mine` resolves to the caller's own desk and never to the
  `{desk_id}` route (the static path must be registered before the
  parameterized path).
- `archive` sets `ARCHIVED`, pauses every follower, and a later transition
  returns 409.
- Order tagging: the owner's order with `desk_id` returns 201; a second user's
  order with that `desk_id` returns 403 `DESK_ORDER_FORBIDDEN`; an order with
  `desk_id` while the desk is not `ACTIVE` returns 409 `DESK_NOT_ACTIVE`; an
  anonymous request returns 401; an unknown `desk_id` returns 404.

`tests/test_desk_follow.py`

- Following an `ACTIVE` desk returns 201; following it twice returns 409
  `DESK_ALREADY_FOLLOWED`; following a `DRAFT` desk returns 409
  `DESK_NOT_ACTIVE`; the owner following their own desk returns 409
  `DESK_SELF_FOLLOW`; an unknown desk returns 404; an anonymous request
  returns 401.
- A `copy_ratio` of `0` and a `copy_ratio` of `1.5` each return 422
  `COPY_RATIO_OUT_OF_RANGE`; `max_total_pct` below `max_per_market_pct` returns
  422 `CAP_OUT_OF_RANGE`; a follower with `2.0000` available returns 422
  `INSUFFICIENT_BALANCE`.
- `PUT` when not following returns 404 `FOLLOW_NOT_FOUND`; `DELETE` returns
  204 and a second `DELETE` returns 404.
- A follower must not read another follower's copy jobs and a third party must
  not read a desk's follower list: both return 403, and a cross-user desk read
  returns 403.

`tests/test_copy_engine.py`

- One desk fill produces exactly one copy job per active follower with the
  shares and cost from the worked sizing example, and the follower's order
  carries `copy_source_fill_id`.
- Running the copy engine twice for the same source fill produces exactly one
  copy order, and `count(CopyJob where follower_user_id and source_fill_id)` is
  one.
- A paused follower receives no copy job.
- Insufficient funds yields `SKIPPED_INSUFFICIENT_FUNDS` and leaves
  `balance`, `locked_balance` and the collateral ledger unchanged.
- A cap-truncated copy stores the truncated `target_shares`, sets
  `limit_breached`, and when the remainder is below `min_order_size` yields
  `SKIPPED_LIMIT_BREACHED`.
- A source price more than `DESK_STALENESS_BPS` away from the reference price
  yields `SKIPPED_STALE` and places no order.
- A non-`ACTIVE` market yields `SKIPPED_MARKET_CLOSED`.
- An empty reference side yields `SKIPPED_NO_LIQUIDITY`.
- A copy of a copy is refused: a fill whose order has `copy_source_fill_id` set
  produces no new copy job.
- No desk share, unit, or net-asset-value row is created by any copy job, and
  the follower's `balance + locked_balance` changes only through `LOCK`,
  `RELEASE` and `FEE` ledger entries.

`tests/test_desk_track_record.py`

- The two-position worked example above returns exactly `cost_basis_usdc`,
  `payout_usdc`, `realized_pnl_usdc`, `net_pnl_usdc`, `closed_positions`,
  `winning_positions`, `win_rate`, `roi_pct`, `avg_win_usdc`, `avg_loss_usdc`
  and `max_drawdown_pct` as stated.
- A desk with no settled positions returns zeroed fields and HTTP 200 rather
  than an error, and `win_rate` is `0.0000`.
- The public list sorts by `roi_pct` by default, an unknown `sort` returns 422,
  `limit` above 100 is clamped, and a non-`ACTIVE` desk returns 404.

`tests/test_desk_risk_controls.py`

- While the desk holds a non-zero position in a market, the operator's
  untagged order in that market returns 409 `DESK_MARKET_CONFLICT`, while a
  desk-tagged order in the same market returns 201.
- The drawdown breaker sets `SUSPENDED` when the rolling 30-day realized
  drawdown is at or below the configured threshold.
- A desk-tagged order that cannot lock its cost sets `SUSPENDED` with
  `review_note=INSUFFICIENT_OPERATOR_FUNDS`.

## Definition of done

The work is complete when all of the following hold:

1. Every test above is present as an automated pytest integration test and all
   automated tests pass, including the pre-existing suite and
   `tests/test_route_baseline.py`, with zero failures.
2. `pytest -q` passes and a static check of undefined names and parse errors
   (`ruff check app tests --select F821,F811,E9`) reports no findings.
3. The application starts successfully from `app/main.py` with no import
   error, and no background server process is left running.
4. `cd frontend && npm run build` completes with zero TypeScript errors and a
   successful production bundle.
5. Contract verification passes: the desk and copy routes are declared in the
   Githeri spec and report as matched, with no missing route.
6. All money, price, fee, share and cap values use Decimal and `Numeric`
   columns, and no binary floating point arithmetic is used for them.
7. The new environment variables are documented, the README describes the
   product and its disclosure rules, and existing auth, order, collateral,
   position and settlement behavior is unchanged.
