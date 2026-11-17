# Resolution & Oracle

AlgoXen resolves markets through an **automated optimistic oracle** backed by **pre-trade Oracle Clarity scoring** and **verifiable price feeds**.

---

## 1. Resolution Lifecycle

1. **Close Market (`CLOSED`)**: When a market's end time passes, trading closes automatically and any resting open limit orders are cancelled with locked funds released.
2. **Propose Outcome (`IN_RESOLUTION`)**: Markets configured with a price feed (such as `gate:BTC_USDT` or `coingecko:bitcoin`) automatically evaluate the closing price and propose the winning outcome, opening a **2-hour dispute window**.
3. **Dispute (`DISPUTED`, optional)**: During the 2-hour window, any signed-in trader can challenge a proposed outcome by staking a **100 AGX counter-bond** on the **Resolution** page. Disputed markets pause for manual review; if your dispute is upheld, your 100 AGX stake is returned plus a **20% AGX reward**.
4. **Finalize (`RESOLVED`)**: Uncontested proposals finalize automatically once the 2-hour window expires. Winning shares redeem 1:1 for **$1.00 USDC** (`$0.00` for losing shares), and AMM liquidity providers can claim their pool share via **Redeem LP**.

---

## 2. Automated Price Feeds

Community and local markets can attach a deterministic feed at creation:
- Supported providers: `gate:<PAIR>` (e.g. `gate:BTC_USDT`) and `coingecko:<COIN_ID>` (e.g. `coingecko:bitcoin`).
- Rule format: `observed_value <comparator> threshold` (`>=`, `>`, `<=`, `<`) → resolves `YES` or `NO`.
- Every automated proposal attaches verifiable proof (feed name, observed value, threshold, source URL, and timestamp) directly on the **Resolution** page.

---

## 3. Resolution Page

Visit **Resolution** in the top navigation to view:
- Markets currently in their 2-hour challenge window or under dispute.
- Proposed winning outcome, bond details (`100 AGX` to dispute), and live countdown timer.
- **Oracle Proof / Evidence** showing the exact price observation and source URL.
- **Stake 100 AGX Counter-Bond & Dispute** button while a proposal is active.
