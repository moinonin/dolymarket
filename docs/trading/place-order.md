# Place an Order (`TradeTicket`)

The order ticket (`frontend/src/components/TradeTicket.tsx`) lives on every event page (`#event/<slug>`) and supports three execution modes, real-time microstructure health telemetry, and AGX fee-discount previews.

---

## 1. Execution Modes

| Mode | Backend Route | Behavior |
|---|---|---|
| **Market** | `POST /api/v4/prediction/orders` (`type: MARKET`) | Crosses the CLOB immediately at best resting bids/asks. |
| **Limit** | `POST /api/v4/prediction/orders` (`type: LIMIT`) | Rests on the CLOB at your tick-aligned price (`$0.01`–`$0.99`). Supports **Post-only** maker guarantee. |
| **Smart Route** | `POST /api/v4/prediction/orders/smart` | Atomically splits/sweeps across resting **CLOB** liquidity and the market's **LMSR AMM pool** (`app/services/router.py`). |

### Smart Route Preview (`POST /api/v4/prediction/orders/smart-quote`)
When **Smart Route** is selected and a share size is entered, the ticket debounces a live quote preview showing:
- **CLOB leg**: Shares filled from resting CLOB orders at prices at least as good as the AMM marginal price.
- **AMM leg**: Remaining shares routed to `AmmPool`.
- **Blended avg**: Volume-weighted blended execution price across both venues.
- **`AMM Backstop Active` badge**: Appears when CLOB depth is empty or exhausted (for example when market makers halt on high toxicity or near expiry), confirming guaranteed exit/entry liquidity via the AMM.

---

## 2. Market Health & Toxicity Shield

At the top of `TradeTicket`, a live telemetry bar polls `GET /api/v1/feargreed/latest?profile=microstructure`:
- **Health Regime**: `STABLE` (emerald), `ELEVATED` (amber, `EWI >= 0.45`), or `CRITICAL` (rose, `EWI >= 0.75`), alongside the numeric **EWI** score.
- **Live Spread**: Displayed in cents (`(bestAsk - bestBid) * 100`) or `Thin book` when either side is empty.
- **Retail Toxicity Warning**: In **Market** mode, if `EWI >= 0.45`, spread `>= 6¢`, or the book is one-sided, an explicit amber banner warns traders to switch to **Limit** or **Smart Route** to cap slippage.

---

## 3. Sides, Time-in-Force (TIF) & Post-Only

- **Buy**: Acquires outcome shares (`YES` / `NO`); locks `price × amount` USDC in `CollateralAccount`.
- **Sell**: Disposes of held outcome shares; locks shares until filled or cancelled.
- **Time-in-Force (`GTC` / `IOC` / `FOK`)** with live inline descriptions:
  - **GTC** (*Good-Til-Cancelled*): Rests on book until filled or cancelled.
  - **IOC** (*Immediate-Or-Cancel*): Fills available size immediately and cancels the remainder.
  - **FOK** (*Fill-Or-Kill*): Fills 100% immediately or cancels the entire order.
- **Post-only** (`LIMIT` only): Rejects the order if it would cross the spread, guaranteeing maker status.
- **Self-trade prevention**: Orders that would match your own resting order are rejected by `MatchingEngine`.

---

## 4. Fees, AGX Discounts & Hotkeys

- **Parabolic Fee Model**: `Fee = C × feeRate × p × (1 - p)`.
- **AGX Tier Preview**: If you hold staked AGX, `TradeTicket` displays your active tier (`Bronze` / `Silver` / `Gold`) and taker fee discount rate inside `FeePreview`.
- **Keyboard Hotkeys**: `B` (Buy), `S` (Sell), `Enter` (Submit), `Esc` (Clear inputs).
