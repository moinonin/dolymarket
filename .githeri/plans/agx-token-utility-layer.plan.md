# COMMAND_RUNWAY: agx-token-utility-layer

# Feature
**Name:** agx-token-utility-layer
**Purpose:** Algoxen (AGX) token utility layer for Dolymarket: staking, fee discounts, oracle dispute staking, Pro Desk and market creation gating, epoch-based reward distribution, and on-chain balance sync.
**Reference Specification:** `.githeri/specs/agx-token-utility-layer.spec.yaml`
**Expected Deliverables:**
- `app/models/domain.py` — AGX models: `AgxStake`, `AgxUnstakeCooldown`, `AgxDisputeStake`, `AgxDeskStake`, `AgxMarketStake`, `AgxBalance`, `AgxLedger`, `AgxRewardEpoch`.
- `app/services/agx.py` — staking, unstaking, withdrawal, reward claiming, dispute staking, desk/market gating, epoch distribution, balance sync.
- `app/api/v1/agx.py` — all AGX API routes.
- `app/api/v1/auth.py` or new router registration in `app/main.py`.
- `frontend/src/pages/AgxStakingPage.tsx` — staking dashboard, tier display, reward claiming.
- `frontend/src/api/client.ts` — AGX client methods.
- `tests/test_agx_staking.py`, `tests/test_agx_disputes.py`, `tests/test_agx_rewards.py`, `tests/test_agx_gating.py`, `tests/test_agx_api.py`.

**Dependencies:**
- `fastapi`
- `sqlalchemy`
- `pydantic`
- `pytest`, `pytest-asyncio`
- `httpx`

**Assumptions:**
- AGX is an ERC-20 token with 18 decimals; the local DB tracks balances for fast reads.
- On-chain sync is triggered manually or by an indexer via `POST /api/v1/agx/sync-balance`.
- The existing CollateralAccount and fee system remains unchanged; AGX fee discounts are applied as a multiplier at order execution time.
- Decimal precision (18 decimals) is used for all AGX amounts.

---

# Global Success Criteria
- Staking endpoints enforce the 1 AGX minimum, 7-day lock, and 3-day unstaking cooldown with 18 decimal precision.
- Fee discount calculation correctly applies Tier 1 (100-999 AGX: 5%), Tier 2 (1000-4999 AGX: 10%), and Tier 3 (5000+ AGX: 15%).
- Dispute staking enforces the 100 AGX minimum, limits to 1 active dispute stake per user per market, and correctly processes reward payouts and slashing.
- Desk creation gating (500 AGX locked) and market creation gating (1000 AGX locked until resolution) function correctly.
- Epoch reward distribution calculates proportional payouts based on staked balances across a 24-hour period and remains strictly idempotent per epoch.
- All AGX amounts use Decimal precision; no floating point in any calculation.
- The entire test suite (`pytest tests/`) passes cleanly without regression.
- `githeri verify` passes with 0 missing endpoints.

---

# Phase 1 — Database Models
1. Add `AgxStake` model: user_id, amount (Numeric 36,18), locked_until (datetime), status (ACTIVE/COOLDOWN/WITHDRAWN), created_at, updated_at.
2. Add `AgxUnstakeCooldown` model: user_id, stake_id, amount, cooldown_until, status (PENDING/COMPLETED), created_at.
3. Add `AgxDisputeStake` model: id, user_id, market_id, amount, status (LOCKED/RETURNED/SLASHED/REWARDED), created_at, resolved_at.
4. Add `AgxDeskStake` model: id, user_id, desk_id, amount, status (LOCKED/RETURNED/SLASHED), created_at, resolved_at.
5. Add `AgxMarketStake` model: id, user_id, market_id, amount, status (LOCKED/RETURNED), created_at, resolved_at.
6. Add `AgxBalance` model: user_id (PK), balance (Numeric 36,18), staked_balance (Numeric 36,18), pending_rewards (Numeric 36,18), last_reward_epoch (int), updated_at.
7. Add `AgxLedger` model: id, user_id, kind (enum), amount (Numeric 36,18), reference_id, created_at.
8. Add `AgxRewardEpoch` model: id, epoch_number (unique), total_fees_collected (Numeric 36,18), total_staked_supply (Numeric 36,18), reward_per_token (Numeric 36,18), started_at, ended_at, distributed (bool).
9. Create Alembic migration for all new tables.
10. Run migration against test DB.

# Phase 2 — AGX Service Layer
1. `stake(user_id, amount)` — validate minimum, check balance, create stake, update AgxBalance, record ledger entry.
2. `unstake(user_id, amount)` — check lock period elapsed, create cooldown, update balances.
3. `withdraw(user_id)` — check cooldown elapsed, return funds, update balances.
4. `get_balance(user_id)` — return balance, staked, pending rewards, tier.
5. `get_tier(staked_balance)` — return tier number and fee discount rate.
6. `apply_fee_discount(user_id, fee)` — calculate discounted fee based on tier.
7. `stake_dispute(user_id, market_id, amount)` — validate minimum, check no existing active dispute, lock funds, create dispute stake.
8. `resolve_dispute(market_id, upheld)` — if upheld: return stake + reward to disputer; if rejected: slash stake to treasury.
9. `stake_desk(user_id, desk_id)` — lock 500 AGX, create desk stake.
10. `return_desk_stake(desk_id)` — return locked AGX on archive/rejection.
11. `stake_market(user_id, market_id)` — lock 1000 AGX, create market stake.
12. `return_market_stake(market_id)` — return locked AGX on resolution/close.
13. `sync_balance(user_id, on_chain_balance)` — update local balance from on-chain.
14. `distribute_epoch()` — calculate proportional rewards, create epoch record, mark distributed.
15. `claim_rewards(user_id)` — transfer pending rewards to balance, record ledger.

# Phase 3 — API Routes
1. `POST /api/v1/agx/stake` — stake AGX.
2. `POST /api/v1/agx/unstake` — initiate unstaking.
3. `POST /api/v1/agx/withdraw` — withdraw after cooldown.
4. `GET /api/v1/agx/balance` — get balance, staked, rewards, tier.
5. `GET /api/v1/agx/stakes` — list active stakes.
6. `POST /api/v1/agx/claim-rewards` — claim accumulated rewards.
7. `GET /api/v1/agx/rewards/history` — reward claim history.
8. `GET /api/v1/agx/tiers` — tier info and fee discount.
9. `POST /api/v1/agx/dispute-stake` — stake to dispute.
10. `GET /api/v1/agx/dispute-stakes` — list dispute stakes.
11. `POST /api/v1/agx/sync-balance` — sync on-chain balance.
12. `GET /api/v1/agx/stats` — protocol-wide stats.
13. `POST /api/v1/agx/epochs/distribute` — distribute epoch rewards (admin).
14. `GET /api/v1/agx/epochs` — list reward epochs.

# Phase 4 — Integration
1. Hook fee discount into order execution: call `apply_fee_discount` when calculating taker fee.
2. Hook dispute staking into resolution flow: require AGX stake to dispute.
3. Hook desk creation gating: require AGX stake before creating desk.
4. Hook market creation gating: require AGX stake before creating market.
5. Add AGX balance display to Portfolio page.
6. Add AGX staking dashboard page.

# Phase 5 — Verification
1. `tests/test_agx_staking.py` — stake/unstake/withdraw lifecycle, minimums, cooldowns.
2. `tests/test_agx_disputes.py` — dispute stake lifecycle, slashing, rewards.
3. `tests/test_agx_rewards.py` — epoch distribution, claiming, idempotency.
4. `tests/test_agx_gating.py` — desk and market creation gating.
5. `tests/test_agx_api.py` — all API endpoints.
6. `pytest -q` — all tests pass.
7. `ruff check app tests --select F821,F811,E9` — clean.
8. `githeri verify` — 0 missing endpoints.

---

# Global Success Criteria
- All AGX models created with Decimal(36,18) precision.
- All staking/unstaking/withdrawal flows work with proper validation.
- Fee discounts applied correctly by tier.
- Dispute staking lifecycle (lock, resolve, slash, reward) works.
- Desk and market creation gating works.
- Epoch reward distribution is proportional and idempotent.
- All Decimal precision maintained (no float in calculations).
- `pytest tests/`, `ruff check`, `githeri verify` all pass.

---

# Environment Variables
- `AGX_TOKEN_ADDRESS`: ERC-20 contract address
- `AGX_CHAIN_ID`: chain ID (default 42161 for Arbitrum)
- `AGX_RPC_URL`: RPC endpoint
- `AGX_MIN_STAKE`: minimum stake (default 1)
- `AGX_UNSTAKE_COOLDOWN_DAYS`: cooldown period (default 3)
- `AGX_MIN_STAKE_LOCK_DAYS`: minimum lock (default 7)
- `AGX_DISPUTE_MIN_STAKE`: minimum dispute stake (default 100)
- `AGX_DESK_MIN_STAKE`: desk creation stake (default 500)
- `AGX_MARKET_MIN_STAKE`: market creation stake (default 1000)
- `AGX_REWARD_EPOCH_HOURS`: epoch duration (default 24)
- `AGX_FEE_DISCOUNT_TIER_1`: tier 1 threshold (default 100)
- `AGX_FEE_DISCOUNT_TIER_2`: tier 2 threshold (default 1000)
- `AGX_FEE_DISCOUNT_TIER_3`: tier 3 threshold (default 5000)
- `AGX_FEE_DISCOUNT_RATE_1`: tier 1 rate (default 0.05)
- `AGX_FEE_DISCOUNT_RATE_2`: tier 2 rate (default 0.10)
- `AGX_FEE_DISCOUNT_RATE_3`: tier 3 rate (default 0.15)