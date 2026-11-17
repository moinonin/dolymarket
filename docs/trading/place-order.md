# Place an Order

The order ticket appears on every event page and supports three execution modes, live market health telemetry, and AGX fee-discount previews.

---

## 1. Execution Modes

| Mode | Behavior |
|---|---|
| **Market** | Executes immediately against the best resting bids/asks in the order book. |
| **Limit** | Rests on the order book at your chosen tick-aligned price (`$0.01`–`$0.99`). Supports **Post-only**. |
| **Smart Route** | Splits execution across resting order book depth and the market's AMM liquidity pool for best blended price. |

When **Smart Route** is selected, a live quote preview shows the order-book leg, AMM leg, and blended average price.

---

## 2. Market Health & Toxicity Shield

At the top of the order ticket, a live telemetry bar shows:
- **Health Regime**: `STABLE`, `ELEVATED`, or `CRITICAL` alongside the market stress score.
- **Live Spread**: Shown in cents or `Thin book` when one side is empty.
- **Retail Toxicity Warning**: In **Market** mode, an amber warning appears when volatility or spread is wide, suggesting **Limit** or **Smart Route** to cap slippage.

---

## 3. Sides, Time-in-Force & Post-Only

- **Buy**: Acquires outcome shares (`YES` / `NO`); locks `price × amount` USDC until filled or cancelled.
- **Sell**: Sells held outcome shares; locks shares until filled or cancelled.
- **Time-in-Force**:
  - **GTC** (*Good-Til-Cancelled*): Rests on the book until filled or cancelled.
  - **IOC** (*Immediate-Or-Cancel*): Fills available size immediately and cancels the rest.
  - **FOK** (*Fill-Or-Kill*): Fills 100% immediately or cancels the entire order.
- **Post-only** (`Limit` only): Ensures your order rests on the book as a maker instead of crossing the spread.
- **Self-trade prevention**: Orders that would match your own resting order are automatically rejected.

---

## 4. Fees, AGX Discounts & Hotkeys

- **Parabolic Fee Model**: `Fee = C × feeRate × p × (1 - p)`.
- **AGX Tier Preview**: Staked AGX unlocks taker-fee discounts (`5%` Bronze, `10%` Silver, `15%` Gold) previewed directly on the ticket.
- **Keyboard Hotkeys**: `B` (Buy), `S` (Sell), `Enter` (Submit), `Esc` (Clear inputs).
