# AGX Utility Token & Staking (`#agx`)

**AGX (Algoxen)** is a complementary 18-decimal utility token (`app/services/agx.py`, `app/api/v1/agx.py`). Zero-AGX users remain **Tier 0** and trade, fund, and settle normally without holding AGX.

---

## 1. Staking Tiers & Taker Fee Discounts (`AgxStakingPage`)

`AgxStakingPage` (`frontend/src/pages/AgxStakingPage.tsx`) connects to `/api/v1/agx/*` (`Decimal`-string wire format):

| Tier | Name | Minimum Staked AGX | Taker Fee Discount |
|---|---|---|---|
| `0` | None | `0` | `0%` |
| `1` | Bronze | `100` | `5%` |
| `2` | Silver | `1,000` | `10%` |
| `3` | Gold | `5,000` | `15%` |

- **CLOB Wiring**: Every CLOB fill (`app/engine/clob.py`) calls `agx.apply_fee_discount()` on the taker fee (falling back cleanly to base fee if AGX is unavailable).
- **Unstake Cooldown**: Unstaking enters a 7-day cooldown (`AgxUnstakeCooldown`) with live progress bars on `#agx` before `Withdraw` returns AGX to spendable balance.

---

## 2. Protocol Fee Accrual & Automated 24h Epochs

- **CLOB + AMM Fee Flow**:
  - CLOB fills record `taker_fee + maker_fee` into the open `AgxRewardEpoch` (using `begin_nested` on SQLite/Postgres and direct call on Turso libSQL).
  - AMM trades (`app/services/amm.py`) split the `1%` fee **50/50** between `AmmPool.fees_collected_usdc` (LPs) and `agx.record_fee(..., creator_user_id=market.creator_user_id)`.
- **Distribution Split**: Each epoch allocates **40%** to market creators (`creator_share`) and **60%** to AGX stakers (`staker_pool`, pro-rata by staked balance).
- **Automated Rollover**: A lifespan background task (`app/main.py`) runs `agx.distribute_matured_epochs()` every 15 minutes to distribute any epoch older than 24 hours; admins can also trigger `POST /api/v1/agx/epochs/distribute`.

---

## 3. Gating Bonds & Dispute Staking

- **Pro Desk Bond**: `500 AGX` locked via `ensure_desk_bond` (`app/api/v1/desks.py`).
- **Optional Community Market Bond**: `1,000 AGX` opt-in via `bond_with_agx: true` on `POST /api/v4/prediction/community/markets` (`ensure_market_bond`).
- **Dispute Staking**: Users can post AGX dispute stakes via `POST /api/v1/agx/dispute-stake`.
- **On-Chain Reconciliation**: `POST /api/v1/agx/sync-balance` credits only the net positive delta over cumulative verified deposits.
