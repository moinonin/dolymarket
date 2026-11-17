# AGX Utility Token & Staking

**AGX** is AlgoXen's utility token for trading fee discounts, 24-hour fee-sharing epochs, and oracle dispute bonds. Users without AGX remain **Tier 0** and can still trade, fund markets, and settle positions normally.

---

## 1. Staking Tiers & Taker Fee Discounts

Visit **AGX** in the top navigation to stake or manage AGX:

| Tier | Name | Minimum Staked AGX | Taker Fee Discount |
|---|---|---|---|
| `0` | None | `0` | `0%` |
| `1` | Bronze | `100` | `5%` |
| `2` | Silver | `1,000` | `10%` |
| `3` | Gold | `5,000` | `15%` |

- **Automatic Discounts**: Your staked tier automatically discounts taker fees on order-book fills.
- **Unstake Cooldown**: Unstaking enters a **7-day cooldown** before AGX returns to your spendable balance.

---

## 2. Fee Sharing & 24-Hour Reward Epochs

- **Fee Pool**: Order-book trading fees and **50%** of the `1%` AMM pool fee accrue into the active 24-hour reward epoch (the other **50%** of AMM fees go directly to pool LPs).
- **Distribution Split**: Each matured 24-hour epoch distributes **40%** to market creators and **60%** pro-rata to AGX stakers.

---

## 3. Gating Bonds & Dispute Staking

- **Dispute Counter-Bond**: Challenging a proposed market resolution on the **Resolution** page requires locking **100 AGX**. If the dispute is upheld, your 100 AGX is returned plus a **20% AGX reward**; if rejected, the stake is forfeited.
- **Pro Desk Bond**: `500 AGX` bond when creating/activating a Pro Desk (when held).
- **Optional Community Market Bond**: Creators may optionally stake a `1,000 AGX` bond when launching a Community Market.
