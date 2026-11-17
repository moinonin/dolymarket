# Portfolio & Pro Position Controls (`#portfolio`)

`PortfolioPage` (`frontend/src/pages/PortfolioPage.tsx`) is the central workspace for positions, cost-basis P&L, order management, ledger auditing, and non-custodial broker transfers.

---

## 1. Summary Strip & AGX Utility Bar

Top KPI cards display real-time aggregates:
- **Portfolio Value**: `sum(shares × mark_price) + cash_balance`.
- **Available USDC**: Total cash balance with quick **Deposit** trigger (`CashLedgerModal`).
- **In open orders**: Collateral locked by resting buy orders.
- **Unrealized PnL**: Aggregate mark-to-market profit/loss across open positions.
- **Open Orders**: Count of active resting orders.

Directly below sits the **AGX Utility Strip**, showing active AGX tier, fee discount rate, staked balance, and a shortcut to `#agx`.

---

## 2. Portfolio Tabs

| Tab | Contents & Actions |
|---|---|
| **Positions** | Active share holdings with `Shares`, `Entry`, **`Cost Basis`** (`shares × avg_entry_price`), `Current`, `Value`, `Unrealized PnL ($ / %)`, and one-tap controls: **`TP +20%`**, **`Reverse`**, and **`Close`**. |
| **Settled** | Resolved positions showing winning outcome and 1:1 `$1.00 USDC` redemption CTA (`POST /api/v4/prediction/positions/redeem`). |
| **Orders** | Active resting orders (`OPEN` / `PARTIAL`) with single and batch cancel controls. |
| **Trades** | Personal execution history (`TradeFill` records with price, shares, and fees). |
| **Ledger** | Immutable `CollateralLedgerEntry` audit log (`DEPOSIT`, `WITHDRAWAL`, `LOCK`, `RELEASE`, `FEE`, `PAYOUT`). |
| **Broker Account** | `DexBuilderBrokerPanel` — live on-chain **Wallet USDC**, **Deposit USDC**, **Withdraw USDC**, **Claim all** winnings, account book, and explorer-linked deposit/withdrawal history. |
| **Security** | Connected Web3 wallet binding and WebAuthn Passkey management. |

---

## 3. One-Tap Position Controls

- **`TP +20%`**: Places a resting `GTC` `SELL` `LIMIT` order at `min($0.99, round(current_price × 1.20, 2))` for your full position size.
- **`Reverse`**: Atomically closes your held outcome via `POST /api/v4/prediction/orders/smart` (`SELL`) and buys the opposite outcome token (`BUY`) for the same share count via **Smart Route**.
- **`Close`**: Attempts full-set CTF merge back into USDC (`POST /api/v4/prediction/positions/merge`), or falls back to an `IOC` `SELL` order on the book.
