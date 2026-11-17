# Portfolio & Position Controls

**Portfolio** is your central workspace for positions, cost-basis P&L, order management, transaction ledger, and wallet transfers.

---

## 1. Summary Strip & AGX Utility Bar

Top KPI cards display real-time aggregates:
- **Portfolio Value**: Total estimated value of open shares plus available cash balance.
- **Available USDC**: Free cash balance with quick **Deposit** trigger.
- **In open orders**: Collateral reserved by resting buy orders.
- **Unrealized PnL**: Mark-to-market profit/loss across open positions.
- **Open Orders**: Count of active resting orders.

Directly below sits the **AGX Utility Strip**, showing your active AGX tier, taker fee discount rate, staked balance, and a shortcut to **AGX**.

---

## 2. Portfolio Tabs & Sub-Tabs

| View | Contents & Actions |
|---|---|
| **Positions** | Active share holdings with `Shares`, `Entry`, `Cost Basis`, `Current`, `Value`, `Unrealized PnL ($ / %)`, and one-tap **`TP +20%`**, **`Reverse`**, and **`Close`** controls. |
| **Settled** *(sub-tab)* | Resolved positions showing the winning outcome and 1:1 `$1.00 USDC` redemption button. |
| **Orders** | Active resting orders (`OPEN` / `PARTIAL`) with single and batch cancel controls. |
| **Trades** *(sub-tab)* | Personal fill history with price, shares, and fees paid. |
| **Ledger** | Complete audit log of deposits, withdrawals, locks, releases, fees, and payouts. |
| **Broker Account** | Connected on-chain wallet USDC balance, **Deposit USDC**, **Withdraw USDC**, and **Claim all** winnings. |
| **Security** | Connected Web3 wallet binding and Passkey (biometric / security key) management. |

---

## 3. One-Tap Position Controls

- **`TP +20%`**: Places a resting `GTC` `SELL` limit order at 20% above the current price (capped at `$0.99`) for your full position.
- **`Reverse`**: Closes your held outcome and buys the opposite outcome for the same share count via **Smart Route**.
- **`Close`**: Merges full outcome sets back into USDC where held, or sells remaining shares on the book.
