# Feature

Name: agx-token-utility-layer

Purpose: Algoxen (AGX) utility layer for the existing Dolymarket CLOB. Adds a double-entry AGX ledger with four balance buckets, staking behind a 7-day lock and 3-day cooldown, tiered taker-fee discounts, 100 AGX optimistic-oracle dispute bonds with slash-to-treasury, gating bonds for Pro Desks and official markets, and idempotent 24-hour epoch fee distribution splitting 40 percent to creators and 60 percent to stakers. AGX is purely complementary: every USDC trading, collateral, settlement and resolution path keeps working for a user holding zero AGX.

Reference Specification: Task `agx-token-utility-layer` (Archetype: `transactional_ledger`)

Expected Deliverables:
- AGX SQLAlchemy models appended to `app/models/domain.py`: `AgxBalance`, `AgxStake`, `AgxUnstakeCooldown`, `AgxDisputeStake`, `AgxDeskStake`, `AgxMarketStake`, `AgxRewardEpoch`, `AgxLedger`.
- Full AGX service surface in `app/services/agx.py`: `stake`, `unstake`, `withdraw`, `get_balance`, `get_tier`, `apply_fee_discount`, `stake_dispute`, `resolve_dispute`, `lock_desk_gating`, `release_desk_gating`, `lock_market_gating`, `release_market_gating`, `sync_balance`, `distribute_epoch`, `claim_rewards`.
- Taker-fee discount hook inside `app/engine/clob.py` that leaves the maker fee and the matching loop untouched.
- AGX router in `app/api/v1/agx.py` with fourteen routes, mounted in `app/main.py`.
- 500 AGX activation bond enforced in the existing `POST /api/v1/desks/` handler.
- Staking dashboard `frontend/src/pages/AgxStakingPage.tsx` mounted at `/agx`, plus AGX fields in `frontend/src/components/TradeTicket.tsx`, `frontend/src/pages/PortfolioPage.tsx` and typed methods in `frontend/src/api/client.ts`.
- Six test modules: `tests/test_agx_staking.py`, `tests/test_agx_disputes.py`, `tests/test_agx_rewards.py`, `tests/test_agx_gating.py`, `tests/test_agx_api.py`, `tests/test_agx_zero_token_regression.py`.

Dependencies:
- Existing FastAPI + React + SQLAlchemy + SQLite (`aiosqlite`) brownfield codebase.
- Existing collateral service (`app/services/collateral.py`), matching engine (`app/engine/clob.py`) and auth dependencies (`app/api/deps.py`).
- Existing route baseline `.githeri/baseline.json` remains the regression contract.

Assumptions:
- The change is strictly additive; no endpoint in `.githeri/baseline.json` is removed or renamed.
- AGX amounts are decimal strings at every JSON boundary and `decimal.Decimal` in Python.
- Error responses carry a stable UPPER_SNAKE code in `detail`.
- On-chain balances enter the platform only through the verified sync route.

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
AGX_CHAIN_ID="42161"
AGX_TOKEN_ADDRESS="0x000000000000000000000000000000000000a6x0"
AGX_TREASURY_ADDRESS="0x0000000000000000000000000000000000007ea5"
AGX_MIN_STAKE="1"
AGX_MIN_STAKE_LOCK_DAYS="7"
AGX_UNSTAKE_COOLDOWN_DAYS="3"
AGX_FEE_DISCOUNT_RATE_1="0.05"
AGX_FEE_DISCOUNT_RATE_2="0.10"
AGX_FEE_DISCOUNT_RATE_3="0.15"
AGX_DISPUTE_MIN_STAKE="100"
AGX_DISPUTE_REWARD_PCT="0.20"
AGX_DESK_MIN_STAKE="500"
AGX_MARKET_MIN_STAKE="1000"
AGX_COMMUNITY_BOND_USDC="50.0000"
AGX_TIER2_BOND_DISCOUNT="0.50"
AGX_REWARD_EPOCH_HOURS="24"
AGX_CREATOR_FEE_SHARE="0.40"
AGX_STAKER_FEE_SHARE="0.60"
```

---

# Global Success Criteria

1. **Zero-Token Invariant (G1)**: A user with no `AgxBalance` row can register, deposit USDC, place and match orders, withdraw collateral and redeem a settled position, all with 2xx responses and unchanged base fees.
2. **Ledger Conservation (G2)**: Every AGX mutation writes exactly one `AgxLedger` row and the ledger sum for a user equals the sum of that user's four buckets at all times.
3. **Stake Lock And Cooldown (G3)**: Unstake before `locked_until` returns 422 `AGX_STAKE_LOCKED`; withdraw before `cooldown_until` returns 422 `AGX_COOLDOWN_ACTIVE`; the lifecycle is `ACTIVE -> COOLDOWN -> WITHDRAWN`.
4. **Tier Discount Ladder (G4)**: Discounts are 0, 5, 10 and 15 percent at the 0, 100, 1000 and 5000 AGX staked thresholds, applied to the taker fee only as `base_fee * (1 - discount)`.
5. **Dispute Determinism (G5)**: One active bond per user and market (409 `AGX_DISPUTE_EXISTS`), upheld returns the bond plus a 20 percent bonus, rejected slashes the full bond to the treasury address.
6. **Gating Thresholds (G6)**: Desk activation requires 500 AGX, official market deployment requires 1000 AGX, and the 50 USDC community bond drops to 25 USDC at Tier 2 and above.
7. **Epoch Idempotency (G7)**: Distribution splits 40/60 exactly, pays each staker `pool * user_stake / total_stake`, and a repeat distribution returns 409 `AGX_EPOCH_ALREADY_DISTRIBUTED` with no ledger writes.
8. **Decimal Precision (G8)**: All AGX values are `Numeric(36, 18)` and `Decimal`, quantized with `ROUND_DOWN` to 18 places, with no float in token math.
9. **Additive Change (G9)**: `pytest tests/test_route_baseline.py` passes and all 115 pre-existing tests remain green.

---

# Execution Stages

## Stage 1: Domain Models

### Objective
Append the AGX persistence entities beside the existing domain models without introducing a second declarative `Base`.

### Inputs
- `app/models/domain.py` with `Base`, `_uuid`, `_now_utc`, `User`, `Market`, `Order`, `Desk`.
- Specification deliverables for `AgxBalance`, `AgxStake`, `AgxUnstakeCooldown`, `AgxDisputeStake`, `AgxDeskStake`, `AgxMarketStake`, `AgxRewardEpoch`, `AgxLedger`.

### Preconditions
- The repository imports cleanly and `app.models.domain` already exposes the existing tables.

### Discovery Tasks
- Read `app/models/domain.py` end to end and list the existing helpers and `Numeric` conventions.
- Confirm `Desk` and `Market` primary keys for foreign keys.

### Execution Tasks
- Append `AgxBalance` with `user_id` as primary key and the four buckets plus `pending_rewards`, `last_reward_epoch`, `updated_at`.
- Append `AgxStake`, `AgxUnstakeCooldown`, `AgxDisputeStake`, `AgxDeskStake`, `AgxMarketStake`, `AgxRewardEpoch`, `AgxLedger`.
- Use `Numeric(36, 18)` for every AGX amount and a unique constraint on `AgxRewardEpoch.epoch_number`.
- Do not redeclare `Base`, `_uuid`, `_now_utc` or reorder existing classes.

### Suggested Commands
```bash
python -c "from app.models.domain import AgxLedger, AgxBalance; print(AgxLedger.__tablename__, AgxBalance.__tablename__)"
```

### Expected Outputs
- `app/models/domain.py` containing the eight AGX entities with fixed-point columns.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1 | `python -c "from app.models.domain import Desk, AgxLedger; print('ok')"` | ok |
| L2 | `python -c "from app.models.domain import AgxBalance; print(AgxBalance.__table__.c.balance.type)"` | NUMERIC(36, 18) |

### Failure Procedure
If verification fails: inspect import errors, confirm helpers were not duplicated, and re-run before touching the service layer.

### Completion Condition
L1 and L2 return the expected output.

---

## Stage 2: AGX Service Layer

### Objective
Implement the fifteen contracted service functions with ledger writes, tier derivation and deterministic token math.

### Inputs
- Stage 1 models.
- Existing `app/services/collateral.py` patterns for session handling and account resolution.

### Preconditions
- Stage 1 completed and models import.

### Discovery Tasks
- Read `app/services/collateral.py` to copy account-resolution, locking and ledger idioms.
- Confirm the async session contract and `for_update` usage.

### Execution Tasks
- Create `app/services/agx.py` with `Q18 = Decimal("0.000000000000000001")`.
- Implement `get_balance` and `get_tier` with the 100 / 1000 / 5000 thresholds.
- Implement `apply_fee_discount(user_id, base_fee, session=None)` returning `base_fee` unchanged when no balance row exists.
- Implement `stake`, `unstake`, `withdraw` with the 1 AGX minimum, 7-day lock and 3-day cooldown.
- Implement `stake_dispute` and `resolve_dispute` with one-active-bond enforcement, 20 percent bonus and treasury slash.
- Implement `lock_desk_gating`, `release_desk_gating`, `lock_market_gating`, `release_market_gating`.
- Implement `sync_balance` enforcing the verified deposit ceiling.
- Implement `distribute_epoch` and `claim_rewards` with 40/60 split, proportional payout and idempotency.
- Emit exactly one `AgxLedger` row per mutation with `balance_after` equal to the post-mutation bucket total.

### Suggested Commands
```bash
python -c "import app.services.agx as a; print([f for f in ('stake','unstake','withdraw','apply_fee_discount','distribute_epoch') if hasattr(a,f)])"
```

### Expected Outputs
- `app/services/agx.py` with the complete function surface and no float arithmetic.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L3 | `python -c "from app.services import agx; print(agx.apply_fee_discount.__name__)"` | apply_fee_discount |

### Failure Procedure
If verification fails: check for circular imports against `app.models.domain`, then re-run.

### Completion Condition
L3 passes and no `float(` remains in `app/services/agx.py`.

---

## Stage 3: Matching Engine Hook And Desk Gate

### Objective
Apply the tier discount to the taker fee during fill settlement and enforce the desk activation bond.

### Inputs
- Stage 2 service.
- `app/engine/clob.py` `_execute_fill`, `compute_fee`, `fee_rate_for_category` and the collateral settlement block.
- `app/api/v1/desks.py` desk creation handler.

### Preconditions
- The existing fee computation and settlement paths are unchanged and passing.

### Discovery Tasks
- Locate the single place where `taker_fee` is computed and charged inside `_execute_fill`.
- Locate the desk creation handler and its commit point.

### Execution Tasks
- Keep `base_taker_fee = compute_fee(qty, fee_rate, fill_price)` and replace only the taker charge with `await agx.apply_fee_discount(taker.user_id, base_taker_fee, session=session)`.
- Leave `maker_fee`, the price-time priority loop, reservation and release logic untouched.
- Import `agx` lazily inside the engine module if a top-level import would create a cycle.
- Add the 500 AGX gate to `POST /api/v1/desks/`, returning 409 `AGX_INSUFFICIENT_GATE` before commit.
- Allow the gate to pass when the caller's `locked_gating_balance` is at least 500.

### Suggested Commands
```bash
python -c "import inspect, app.engine.clob as c; print('apply_fee_discount' in inspect.getsource(c))"
```

### Expected Outputs
- `app/engine/clob.py` with a taker-only discount hook.
- `app/api/v1/desks.py` enforcing the activation bond.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L4 | `grep -c "apply_fee_discount" app/engine/clob.py` | 1 or more |
| L7 | `grep -c "AGX_INSUFFICIENT_GATE" app/api/v1/desks.py` | 1 or more |

### Failure Procedure
If verification fails: confirm the hook is inside `_execute_fill` and not the matching loop, then re-run.

### Completion Condition
L4 and L7 pass and `pytest tests/test_clob_engine.py` stays green.

---

## Stage 4: AGX Routes

### Objective
Expose the fourteen AGX routes and mount the router additively.

### Inputs
- Stage 2 service and Stage 1 models.
- `app/api/deps.py`, `app/db/session.py`, existing router conventions in `app/api/v1/desks.py`.

### Preconditions
- Service functions callable and error codes defined.

### Discovery Tasks
- Read `app/api/v1/desks.py` for prefix, dependency and error idioms.
- Read `app/main.py` import block and `include_router` ordering.

### Execution Tasks
- Create `app/api/v1/agx.py` with `APIRouter(prefix="/api/v1/agx", tags=["agx"])`.
- Implement stake, unstake, withdraw, balance, stakes, claim-rewards, rewards/history, tiers, dispute-stake, dispute-stakes, sync-balance, stats, epochs/distribute and epochs.
- Serialize every AGX amount as a decimal string.
- Return 401 for anonymous callers, 403 for foreign-resource access, 404 for unknown ids, 409 for state conflicts and 422 for lock, cooldown and minimum violations.
- Mount the router in `app/main.py` beside the existing `include_router` calls.

### Suggested Commands
```bash
python -c "from app.main import app; print(sorted({r.path for r in app.routes if '/agx' in r.path}))"
```

### Expected Outputs
- `app/api/v1/agx.py` with all fourteen routes.
- `app/main.py` mounting `agx_router`.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L5 | `python -c "from app.main import app; print(len({r.path for r in app.routes if '/agx' in r.path}))"` | 14 |
| L6 | `python -c "from app.main import app; assert any('/agx/balance' == r.path for r in app.routes)"` | no assertion error |

### Failure Procedure
If verification fails: inspect route ordering and dependency wiring, then re-run.

### Completion Condition
L5 and L6 pass.

---

## Stage 5: Frontend Surface

### Objective
Ship the AGX dashboard and surface tier discounts and balances in the existing trading UI.

### Inputs
- Stage 4 route contract.
- `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/components/TradeTicket.tsx`, `frontend/src/pages/PortfolioPage.tsx`.

### Preconditions
- Backend routes respond with decimal-string payloads.

### Discovery Tasks
- Read `frontend/src/api/client.ts` to copy the request helper and error handling.
- Read `frontend/src/App.tsx` hash-route registration and navigation header.

### Execution Tasks
- Add `AgxBalance`, `AgxStake`, `AgxDisputeStake`, `AgxRewardEpoch` types and typed client methods for every AGX route.
- Create `frontend/src/pages/AgxStakingPage.tsx` with tier badge, staked balance, unlock countdown, cooldown progress, fee discount, accrued rewards and stake/unstake forms.
- Handle loading, empty and error states; no mock arrays and no hardcoded localhost URLs.
- Mount `/agx` in `App.tsx` and the navigation header.
- Show the applied discount in `TradeTicket.tsx` for Tier 1 and above and the AGX balance plus tier in `PortfolioPage.tsx`.
- Use `lucide-react` icons for consistency.

### Suggested Commands
```bash
npm --prefix frontend run build
```

### Expected Outputs
- `frontend/src/pages/AgxStakingPage.tsx` and updated client, ticket and portfolio views.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L8 | `grep -c "AgxStakingPage" frontend/src/App.tsx` | 1 or more |
| L9 | `npm --prefix frontend run build` | exit 0 |

### Failure Procedure
If verification fails: resolve TypeScript errors and unused imports, then rebuild. Never start a dev server.

### Completion Condition
L8 and L9 pass with zero TypeScript errors.

---

## Stage 6: Tests And Verification

### Objective
Prove every business rule, boundary and the zero-token invariant, then run the full regression gate.

### Inputs
- Stages 1 through 5.
- `tests/conftest.py` fixtures and `tests/test_route_baseline.py`.

### Preconditions
- Application imports cleanly and routes resolve.

### Discovery Tasks
- Read `tests/conftest.py` for the async client, database and authenticated-user fixtures.
- Read `tests/test_route_baseline.py` to mirror baseline assertions.

### Execution Tasks
- Add `tests/test_agx_staking.py` for stake, 7-day lock, 3-day cooldown, withdrawal and balance integrity.
- Add `tests/test_agx_disputes.py` for the 100 AGX bond, duplicate rejection, upheld bonus and treasury slash.
- Add `tests/test_agx_rewards.py` for the 40/60 split, proportional payouts, 409 duplicate rejection and claiming.
- Add `tests/test_agx_gating.py` for desk and market gates plus real CLOB taker discounts.
- Add `tests/test_agx_api.py` for every route including 401, 403, 404, 409 and 422 boundaries.
- Add `tests/test_agx_zero_token_regression.py` proving trading, collateral and redemption work with no AGX row.
- Run the targeted modules, then the full suite, then the frontend build.

### Security, Ownership And Quota Guards
- [ ] Scope collection queries to the authenticated `user_id`; foreign-resource access returns 403 and unknown ids return 404.
- [ ] Enforce the verified-deposit ceiling so spendable AGX can never be created locally.
- [ ] Keep epoch distribution idempotent under concurrent calls using the unique `epoch_number` and a row lock.
- [ ] Never log or serialize treasury secrets; AGX amounts stay decimal strings.

### Suggested Commands
```bash
pytest tests/test_agx_staking.py tests/test_agx_disputes.py tests/test_agx_rewards.py tests/test_agx_gating.py tests/test_agx_api.py tests/test_agx_zero_token_regression.py
pytest tests/
npm --prefix frontend run build
```

### Expected Outputs
- Six AGX test modules passing.
- Full backend suite passing with the existing 115 tests intact.
- Frontend production bundle with zero errors.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L10 | `pytest tests/test_agx_staking.py` | exit 0 |
| L11 | `pytest tests/test_agx_disputes.py` | exit 0 |
| L12 | `pytest tests/test_agx_rewards.py` | exit 0 |
| L13 | `pytest tests/test_agx_gating.py` | exit 0 |
| L14 | `pytest tests/test_agx_api.py` | exit 0 |
| L15 | `pytest tests/test_agx_zero_token_regression.py` | exit 0 |
| L16 | `pytest tests/test_route_baseline.py` | exit 0 |
| L17 | `pytest tests/` | exit 0 |
| L18 | `npm --prefix frontend run build` | exit 0 |
| L19 | `pytest tests/test_agx_staking.py -k "lock or cooldown"` | exit 0 |

### Failure Procedure
If any check fails: fix the implementation, never the contract. Do not weaken or delete an assertion to pass, and do not modify `.githeri/baseline.json`.

### Completion Condition
L10 through L19 all pass with exit code 0.

---

# Target Files

Backend:
- `app/models/domain.py` (append eight AGX models)
- `app/services/agx.py` (new)
- `app/engine/clob.py` (taker-fee hook only)
- `app/api/v1/agx.py` (new)
- `app/api/v1/desks.py` (activation gate)
- `app/main.py` (router mount)

Frontend:
- `frontend/src/pages/AgxStakingPage.tsx` (new)
- `frontend/src/App.tsx` (route plus navigation)
- `frontend/src/api/client.ts` (typed methods)
- `frontend/src/components/TradeTicket.tsx` (discount line)
- `frontend/src/pages/PortfolioPage.tsx` (balance and tier)

Tests:
- `tests/test_agx_staking.py`
- `tests/test_agx_disputes.py`
- `tests/test_agx_rewards.py`
- `tests/test_agx_gating.py`
- `tests/test_agx_api.py`
- `tests/test_agx_zero_token_regression.py`

---

# Completion Definition

The feature is complete when the application starts cleanly against a fresh database, every AGX route in the specification resolves, L10 through L19 pass with exit code 0, the pre-existing 115 tests are still green, and `githeri verify` reports zero missing endpoints against the contract.
