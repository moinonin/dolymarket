# Feature

Name: pro-desks-copy-trading

Purpose: Pro Desks: non-custodial copy trading. Each desk fill is mirrored proportionally into each follower's own collateral account with deterministic sizing, a deterministic track record, and no pooled capital, share, net-asset-value or result-based fee.

Reference Specification: Task `pro-desks-copy-trading` (Archetype: `transactional_ledger`)

Expected Deliverables:
- Additive SQLAlchemy models in `app/models/domain.py`: `Desk`, `DeskFollower`, `DeskPosition`, and `CopyJob`, plus extensions to `User` (`is_admin`) and `Order` (`desk_id`, `copy_source_fill_id`).
- Deterministic track record calculation service in `app/services/desk_track_record.py`.
- Non-custodial copy trading engine with atomic balance reservation and exactly-once mirroring in `app/services/copy_engine.py`.
- REST API endpoints for desk management, followers, copy-jobs, and track record in `app/api/v1/desks.py`.
- Enhanced order submission endpoint in `app/api/v4/orders.py` with desk tagging and anti-front-running market conflict checks.
- Admin review and desk control endpoints in `app/api/v4/admin.py`.
- Router registration in `app/main.py`.
- Frontend UI components for desk leaderboard and desk detail views in `frontend/src/pages/DesksPage.tsx` and `frontend/src/pages/DeskDetailPage.tsx`.

Dependencies:
- Existing FastAPI + React + SQLAlchemy + SQLite (`aiosqlite`) brownfield codebase.
- Existing collateral service (`app/services/collateral.py`) and order matching engine.
- Existing authentication dependencies (`app/api/deps.py`).

Assumptions:
- The change is strictly additive; existing route contracts in `.githeri/baseline.json` must remain operational without breaking changes.
- Copy orders directly reuse the existing collateral service and matching engine.
- Money, share, price, ratio, and percentage fields strictly use fixed-point Decimal arithmetic and database `Numeric` columns.

---

# Target Environment

Language: Python 3.11+ / TypeScript
Framework: FastAPI (Backend) / React + Vite + Tailwind CSS v4 (Frontend)
ORM: SQLAlchemy (Async IO via `aiosqlite`)
Test Framework: pytest / pytest-asyncio (Backend)
Operating System: Linux / macOS

Environment Variables:
```shell
DATABASE_URL="sqlite+aiosqlite:///:memory:"
JWT_SECRET="test-secret-key-1234567890abcdef"
COPY_TRADING_ENABLED="true"
DESK_MIN_CLOSED_POSITIONS="10"
DESK_MIN_DAYS_ACTIVE="14"
DESK_MIN_COPY_RATIO="0.0100"
DESK_MAX_COPY_RATIO="1.0000"
DESK_DEFAULT_PER_MARKET_CAP_USDC="50.0000"
DESK_MAX_PER_MARKET_EQUITY_PCT="20"
DESK_MAX_TOTAL_EQUITY_PCT="25"
DESK_STALENESS_BPS="200"
DESK_DRAWDOWN_BREAKER_PCT="20"
```

---

# Global Success Criteria

1. **Non-Custodial Copying (G1)**: Every copy order is funded exclusively from the follower's own `CollateralAccount`. No pooled balance, desk shares, or net-asset-value calculations exist.
2. **Atomic Balance Reservation (G2)**: Copy orders lock follower collateral rows using database row locks (`with_for_update`). Orders exceeding `available_usdc` (`balance - locked_balance`) are rejected without balance corruption.
3. **Exact Copy Sizing (G3)**: Sizing follows `budget_usdc = min(gross_cost_usdc, remaining_market, remaining_total, available_usdc)` and `target_shares = budget_usdc / price` truncated to 4 decimal places (`0.0001`).
4. **Exactly-Once Mirroring (G4)**: At most one `CopyJob` is created per `(follower_user_id, source_fill_id)`, enforced by database unique constraints.
5. **Anti Front-Running Guard (G5)**: Active desk operators placing untagged personal orders in a market where their desk holds a non-zero position are rejected with HTTP

### Stage 1: Target Localization & Precondition Check
- [ ] Inspect localized target files (`app/models/domain.py, app/services/collateral.py, app/services/desk_track_record.py, app/services/copy_engine.py, app/api/v1/desks.py, app/api/v4/orders.py, app/api/v4/admin.py, app/main.py, frontend/src/pages/DesksPage.tsx`) and verify preconditions.

### Security, Ownership & Quota Enforcement Guards
- [ ] **Resource Ownership & Query Scoping Guard (`403 Forbidden`)**: Scope collection list queries strictly to the authenticated `user_id` (never leak `anonymous` or other users' rows to authenticated sessions), and enforce ownership checks on `{id}` routes returning `HTTP 403 Forbidden` on cross-user access.
- [ ] **Idempotent Test Database Isolation**: Resolve database/SQLite connection paths dynamically from environment variables inside connection helpers so pytest fixtures run against isolated temporary databases without cross-run state or quota pollution.

### Stage 4: Automated Verification & Test Execution
- [ ] Run verification command: `pytest tests/` and confirm exit code 0.