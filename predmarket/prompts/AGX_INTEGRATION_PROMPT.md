# AGX Token Utility Layer & Prediction Market Integration Prompt

## Part 1: Harmonization Analysis (Mismatches, Contradictions & Resolving Strategy)

| Dimension | `docs/PREDICTION_MARKET_INTEGRATION.md` | `.githeri/specs/agx-token-utility-layer.spec.yaml` | Harmonized Resolution |
| :--- | :--- | :--- | :--- |
| **System Architecture** | On-chain EVM protocol (Arbitrum One, CPMM AMM pools, Foundry contracts, web3 wallets). | Off-chain CLOB backend (FastAPI, SQLite/PostgreSQL, WebAuthn, OAuth, in-memory matching). | **Dual-Rail Architecture**: Dolymarket serves as the high-throughput off-chain execution and matching engine with an on-chain ledger mirror. AGX balance syncs from Arbitrum One (`POST /api/v1/agx/sync-balance`); staking, gating, and fee discounts execute directly inside Dolymarket's CLOB matching engine. |
| **Fee Discount Structure** | Absolute taker fee rates: Tier 0 = 2.0%, Tier 1 = 1.5%, Tier 2 = 1.0%, Tier 3 = 0.5%. No explicit staking volume thresholds specified. | Staking volume thresholds with relative discount percentages: Tier 1 (100–999 AGX) = 5% off, Tier 2 (1,000–4,999 AGX) = 10% off, Tier 3 (5,000+ AGX) = 15% off. | **Harmonized Tier Multiplier**: Adopt explicit staking tiers (100, 1,000, 5,000 AGX) applying relative percentage reductions to Dolymarket's baseline fee schedule via `apply_fee_discount()` in `app/engine/clob.py`. |
| **Staking Locks & Cooldowns** | Unspecified lockup rules; references "locked AGX stakers" for monthly reward distribution. | Concrete rules: Minimum stake 1 AGX, 7-day initial lock (`AGX_MIN_STAKE_LOCK_DAYS`), 3-day unstaking cooldown (`AGX_UNSTAKE_COOLDOWN_DAYS`). | **Adopt Rigorous Lifecycle**: Enforce 7-day initial lock and 3-day cooldown state machine (`AgxStake` and `AgxUnstakeCooldown`). |
| **Fee Split & Reward Cadence** | 40% to Creator, 60% to ALGOXEN stakers routed monthly via on-chain `RewardClaims.sol`. | 24-hour epochs (`AGX_REWARD_EPOCH_HOURS = 24`) distributing accumulated platform fees to stakers proportionally. | **Daily Epoch Revenue Share**: Dolymarket tracks 24-hour reward epochs off-chain for active stakers, allocating 60% of collected protocol taker fees to the staker pool and 40% to market creators, maintaining strict idempotency per epoch. |
| **Dispute Resolution & Bonds** | UMA Optimistic Oracle v3 / Multi-sig dispute window (24–48h); stakers vote on disputes. | Fixed bond: 100 AGX minimum dispute stake; binary outcome (Upheld: bond returned + reward; Rejected: bond slashed to protocol treasury). | **Deterministic Bond Staking**: Implement 100 AGX dispute staking workflow inside the market resolution pipeline (`POST /api/v1/agx/dispute-stake`). Slashed tokens route to the protocol treasury address. |
| **Creation Gating & Bonds** | Creator Bond (50 USDC or AGX equivalent) + Minimum Initial Liquidity (500 USDC) for community markets. | Locking 500 AGX for Pro Desk creation; locking 1,000 AGX for Official Market creation. | **Unified Gating Rules**: (1) Pro Desks require 500 AGX locked; (2) Official/Curated markets require 1,000 AGX locked; (3) Community markets require 50 USDC / AGX anti-spam bond with 50% discount for Tier 2+ AGX stakers. |
| **Numeric Precision** | Standard ERC-20 and USDC collateral references. | Mandates strict `Numeric(36, 18)` in DB and Python `Decimal` across all arithmetic (zero floats). | **Enforce Decimal Precision**: All AGX balances, stakes, fees, and rewards use `Numeric(36, 18)` and Python `decimal.Decimal`. |

---

## Part 2: Holistic L4+ Githeri MCP Integration Prompt

```markdown
# Feature: Algoxen (AGX) Token Utility Layer & Economic Complement

## 1. Change Type and Operating Rules

This is a **brownfield extension** to the existing `dolymarket` repository, **not a new project**. Read the files listed under Context and follow the established conventions before modifying code. Extend existing modules in place:
- Append new AGX models to `app/models/domain.py` beside existing models (`User`, `Market`, `Order`, `Desk`, etc.). Do not create a second declarative `Base`.
- Add the AGX service layer under `app/services/agx.py` following patterns from `app/services/collateral.py` and `app/services/settlement.py`.
- Add the AGX router under `app/api/v1/agx.py` as a sibling to `auth.py`, `collateral.py`, and `desks.py`, and mount it in `app/main.py`.
- Hook fee discount calculations into `app/engine/clob.py` without mutating the core matching loop or breaking existing order execution.
- Add `frontend/src/pages/AgxStakingPage.tsx` and integrate it into `frontend/src/App.tsx` and the navigation header.
- Extend `frontend/src/api/client.ts` with typed methods for `/api/v1/agx/*`.
- Do not scaffold a new project, do not regenerate files from scratch, do not declare a second `FastAPI` instance, and do not remove or rename any existing endpoint in `.githeri/baseline.json`. All 115 existing tests in `pytest tests/` must remain passing.

All AGX amounts must use `Numeric(36, 18)` in SQLAlchemy, `decimal.Decimal` in Python, and string serialization at JSON boundaries. Binary floating point is strictly prohibited for token math.

---

## 2. Invariant: Pure Complementary Utility (Zero Hard Blocking Dependency)

**The prediction market must function normally even without AGX.**
- **Zero-Token Participation**: Users with 0 AGX (Tier 0) trade on the CLOB, deposit/withdraw USDC collateral, hold positions, redeem winning tokens ($1.00/share), and use the platform with zero friction.
- **Graceful Fallbacks**:
  - If a user has 0 AGX or has never interacted with AGX, their taker fee discount multiplier is `0.00` (they pay standard base fees).
  - If AGX balance sync is unconfigured or offline, core USDC order matching and settlement are unaffected.
  - Standard prediction market resolution proceeds through established oracle/admin paths; AGX dispute staking is an optional decentralized escalation path, not a required gate for normal resolution.
- **Gating Boundaries**:
  - Gating applies only to AGX-specific perks: Pro Desk operator staking (500 AGX bond), official curated market deployment (1,000 AGX lock), and creator bond fee subsidies.
  - Regular users creating standard community markets or trading existing markets are never blocked by AGX requirements.

---

## 3. Context & Architecture

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 async.
- **Matching Engine**: In-memory price-time priority CLOB (`app/engine/clob.py`).
- **Collateral & Settlement**: USDC accounts (`app/services/collateral.py`) and conditional token framework (`app/services/settlement.py`).
- **Baseline Endpoints**: Documented in `.githeri/baseline.json` and verified by `tests/test_route_baseline.py`.
- **Token Specifications**:
  - Symbol: `AGX` (Algoxen Token)
  - Decimals: 18
  - Chain ID: 42161 (Arbitrum One, configurable via `AGX_CHAIN_ID`)
  - Contract: Configurable via `AGX_TOKEN_ADDRESS` (default fallback address provided in test environment)

---

## 4. Detailed Functional Specifications

### A. Balance Tracking & Double-Entry Ledger
1. `AgxBalance` entity per user tracking:
   - `balance`: Spendable, unencumbered AGX balance.
   - `staked_balance`: Actively staked AGX generating fee discounts and epoch rewards.
   - `locked_gating_balance`: AGX bonded for Pro Desks or market creation.
   - `locked_dispute_balance`: AGX bonded in active oracle disputes.
   - `pending_rewards`: Accrued, unclaimed USDC or AGX protocol fee shares.
2. `AgxLedger`:
   - Immutable double-entry audit record for every AGX delta: `(user_id, kind, amount, balance_after, reference_id, created_at)`.
   - Kinds: `DEPOSIT`, `WITHDRAWAL`, `STAKE`, `UNSTAKE_COOLDOWN`, `WITHDRAW_STAKE`, `FEE_REWARD`, `DISPUTE_LOCK`, `DISPUTE_RETURN`, `DISPUTE_REWARD`, `SLASH`, `GATING_LOCK`, `GATING_RELEASE`.
3. `POST /api/v1/agx/sync-balance`:
   - Synchronizes on-chain balance with off-chain ledger. Deposits record verified net positive delta. Local spendable balance cannot exceed verified on-chain deposits.

### B. Staking Lifecycle (Locks & Cooldowns)
- **Minimum Stake**: 1 AGX (`AGX_MIN_STAKE = 1`).
- **Lock Duration**: 7 days (`AGX_MIN_STAKE_LOCK_DAYS = 7`). Initiating unstake before 7 days from stake creation rejects with HTTP 422.
- **Cooldown Duration**: 3 days (`AGX_UNSTAKE_COOLDOWN_DAYS = 3`). Unstaking transitions funds to `AgxUnstakeCooldown`.
- **Withdrawal**: Funds can only be withdrawn to spendable balance via `POST /api/v1/agx/withdraw` after the 3-day cooldown has elapsed. Early withdrawal rejects with HTTP 422.
- **Lifecycle States**: `ACTIVE` -> `COOLDOWN` -> `WITHDRAWN`.

### C. CLOB Taker-Fee Discount Engine
Hook `apply_fee_discount(user_id: str, base_fee: Decimal) -> Decimal` into `app/engine/clob.py` during order execution:
- **Tier 0** (0 – 99.99 AGX staked): 0% discount (pays standard fee).
- **Tier 1 (Bronze)** (100 – 999.99 AGX staked): 5% discount (`AGX_FEE_DISCOUNT_RATE_1 = 0.05`).
- **Tier 2 (Silver)** (1,000 – 4,999.99 AGX staked): 10% discount (`AGX_FEE_DISCOUNT_RATE_2 = 0.10`).
- **Tier 3 (Gold / Whale)** (5,000+ AGX staked): 15% discount (`AGX_FEE_DISCOUNT_RATE_3 = 0.15`).
- If user has no `AgxBalance` record, gracefully default to Tier 0 (0% discount).
- Calculations: `effective_fee = base_fee * (Decimal("1.0") - tier_discount)`.

### D. Optimistic Oracle Dispute Staking & Slashing
- **Dispute Stake**: During a market's `CHALLENGE_WINDOW`, users can dispute a proposed outcome by locking 100 AGX (`AGX_DISPUTE_MIN_STAKE = 100`) via `POST /api/v1/agx/dispute-stake`.
- **Constraints**: Maximum 1 active dispute stake per user per market. User must hold >= 100 AGX spendable balance.
- **Upheld Dispute**: If challenge is validated by oracle consensus / admin fallback, the 100 AGX stake is unlocked and returned, plus a 20% reward bonus.
- **Rejected Dispute**: If challenge is rejected (spam/malicious), the 100 AGX stake is `SLASHED` and transferred to the protocol treasury address (`AGX_TREASURY_ADDRESS`). Slashed funds are never returned or shared with regular stakers.

### E. Feature Gating & Anti-Spam Bonds
1. **Pro Desks**: Creating a Pro Desk (`POST /api/v1/desks/`) checks AGX status. Locking 500 AGX (`AGX_DESK_MIN_STAKE`) activates the desk. Locked AGX is refunded upon clean desk archive.
2. **Official Markets**: Deploying an official benchmark market requires locking 1,000 AGX (`AGX_MARKET_MIN_STAKE`), refunded upon final market settlement.
3. **Community Markets**: Standard community markets can be created with 50 USDC anti-spam bond. Stakers with Tier 2+ (1,000+ AGX) receive a 50% discount on the creation bond requirement.

### F. 24-Hour Epoch Fee Distribution (Revenue Sharing)
- **Fee Split**: Prediction market fees collected by the platform are split:
  - 40% to Market Creator (credited to creator account).
  - 60% to AGX Stakers Pool (epoch reward pool).
- **Distribution Cadence**: 24-hour epochs (`AGX_REWARD_EPOCH_HOURS = 24`).
- **Formula**:
  `user_reward = total_epoch_staker_fees * (user_staked_balance / total_staked_supply)`
- **Idempotency**: Epoch distribution is strictly idempotent; attempting to distribute an already distributed epoch returns HTTP 409.
- **Claiming**: Stakers claim accrued rewards via `POST /api/v1/agx/claim-rewards`. Unclaimed rewards accumulate safely across epochs.

---

## 5. Deliverables & File Modifications

### Models (`app/models/domain.py`)
- `AgxBalance`: `user_id` (PK, FK), `balance`, `staked_balance`, `locked_gating_balance`, `locked_dispute_balance`, `pending_rewards`, `last_reward_epoch`, `updated_at`.
- `AgxStake`: `id`, `user_id`, `amount`, `locked_until`, `status` (ACTIVE/COOLDOWN/WITHDRAWN), `created_at`, `updated_at`.
- `AgxUnstakeCooldown`: `id`, `stake_id`, `user_id`, `amount`, `cooldown_until`, `status` (PENDING/COMPLETED), `created_at`.
- `AgxDisputeStake`: `id`, `user_id`, `market_id`, `amount`, `status` (LOCKED/RETURNED/SLASHED/REWARDED), `created_at`, `resolved_at`.
- `AgxDeskStake` & `AgxMarketStake`: Gating lock tracking models.
- `AgxRewardEpoch`: `id`, `epoch_number` (unique), `total_fees_collected`, `total_staked_supply`, `reward_per_token`, `started_at`, `ended_at`, `distributed`.
- `AgxLedger`: Audit log for all AGX balance modifications.

### Service Layer (`app/services/agx.py`)
- Implement: `stake`, `unstake`, `withdraw`, `get_balance`, `get_tier`, `apply_fee_discount`, `stake_dispute`, `resolve_dispute`, `lock_desk_gating`, `release_desk_gating`, `lock_market_gating`, `release_market_gating`, `sync_balance`, `distribute_epoch`, `claim_rewards`.

### API Routes (`app/api/v1/agx.py` mounted in `app/main.py`)
- `POST /api/v1/agx/stake`
- `POST /api/v1/agx/unstake`
- `POST /api/v1/agx/withdraw`
- `GET  /api/v1/agx/balance`
- `GET  /api/v1/agx/stakes`
- `POST /api/v1/agx/claim-rewards`
- `GET  /api/v1/agx/rewards/history`
- `GET  /api/v1/agx/tiers`
- `POST /api/v1/agx/dispute-stake`
- `GET  /api/v1/agx/dispute-stakes`
- `POST /api/v1/agx/sync-balance`
- `GET  /api/v1/agx/stats`
- `POST /api/v1/agx/epochs/distribute`
- `GET  /api/v1/agx/epochs`

### Frontend UI (`frontend/src/`)
- `frontend/src/pages/AgxStakingPage.tsx`: Dedicated dashboard displaying user tier badge, staked balance, unlock countdown, cooldown progress, fee discount rate, accrued epoch rewards, and stake/unstake forms.
- `frontend/src/App.tsx`: Route `/agx` mounted in the navigation bar.
- `frontend/src/components/TradeTicket.tsx`: Display applied AGX tier discount in the fee line if user is Tier 1+.
- `frontend/src/pages/PortfolioPage.tsx`: Display AGX balance and tier status in the asset overview card.
- `frontend/src/api/client.ts`: Typed client integration for all AGX endpoints.

### Tests (`tests/`)
- `tests/test_agx_staking.py`: Lifecycle tests (stake, 7-day lock enforcement, 3-day cooldown enforcement, withdrawal, balance integrity).
- `tests/test_agx_disputes.py`: 100 AGX dispute staking, duplicate checks, slashing to treasury on rejection, bonus payouts on upheld disputes.
- `tests/test_agx_rewards.py`: 24h epoch distribution, proportional calculations, duplicate distribution rejection (HTTP 409), reward claiming.
- `tests/test_agx_gating.py`: Pro Desk and market creation gating, staker tier fee discounts on CLOB taker orders.
- `tests/test_agx_api.py`: Comprehensive REST API route tests.
- `tests/test_agx_zero_token_regression.py`: Explicit regression test proving users with 0 AGX can place orders, match trades, deposit/withdraw USDC, and redeem payouts with zero errors.

---

## 6. Verification Commands

Before completing the task:
1. `pytest tests/` must pass 100% (both new AGX tests and existing 115 tests).
2. `cd frontend && npm run build` must compile with 0 errors.
3. `githeri verify` must confirm 0 missing endpoints against contract specifications.
```
