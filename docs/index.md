# AlgoXen UI & Platform Guide

AlgoXen is a hybrid prediction market platform combining an **off-chain Central Limit Order Book (CLOB)**, an **overflow-safe LMSR Automated Market Maker (AMM)**, **Conditional Tokens Framework (CTF)** settlement, **Pro Desk copy trading & Fear/Greed market making**, and **non-custodial Web3 wallet signing**.

---

## Navigation & Hash Routes

All views are served from the React SPA (`frontend/src/App.tsx`) using hash-based routes:

| Nav / Route | Page Component | Purpose |
|---|---|---|
| `#home` | `HomePage` / `LiveMarketsPage` | Public landing with live Fear & Greed gauge (`HeroVisual`); redirects signed-in users to `#live`. |
| `#markets` | `MarketsPage` | Local Official & Community markets (`Community` / `Unfunded` badges) and community market creation. |
| `#live` | `LiveMarketsPage` | Live DexBuilder prediction markets feed with WebSocket streaming + REST fallback. |
| `#event/<slug>` | `EventDetailPage` | Event markets, `OrderBookLadder`, `RecentTrades`, price chart, and `TradeTicket`. |
| `#market/<id>` | `MarketDetailPage` | Single-market detail with `Oracle Clarity` badge and microstructure telemetry (`Spread`, `$100` impact, `EWI`). |
| `#live/market/<id>` | `LiveMarketDetailPage` | Live DexBuilder market order book, candlesticks, trade tape, and `LiveTradeTicket`. |
| `#portfolio` | `PortfolioPage` | Summary cards, `Positions`, `Settled`, `Orders`, `Trades`, `Ledger`, `Broker Account`, and `Security`. |
| `#desks` / `#desks/<id>` | `DesksPage` / `DeskDetailPage` | Pro Desk leaderboard, track-record equity curves, copy-follow controls, and `DeskMarketMakerPanel`. |
| `#copy` | `CopyActivityPage` | Real-time copy-trading job audit trail and per-market risk cap status. |
| `#agx` | `AgxStakingPage` | AGX staking tiers, fee discounts, 24h reward epochs, unstake cooldowns, and dispute staking. |
| `#resolution` | `ResolutionPage` | Optimistic oracle queue, deterministic feed evidence proofs, and counter-bond disputes. |
| `#tags` / `#trades` / `#settled` | `TagsPage` / `UserTradesPage` / `SettledPositionsPage` | Tag explorer, personal fill history, and redeemed settlements. |
| `#admin` | `AdminPage` | Admin-only console for event/market lifecycle, desk approvals, and copy-job audits. |

---

## Quickstart Flow

1. **Authenticate** via Email + Password, Passkey (WebAuthn), or **Sign In with Ethereum (SIWE)** from the `WalletButton` (`#home` / navbar).
2. **Fund Collateral**:
   - **Simulation mode**: Use `Deposit` on `#portfolio` (`CashLedgerModal` -> `POST /api/v1/collateral/deposit`, gated by `ENABLE_DEMO_COLLATERAL`).
   - **On-chain DexBuilder mode**: Connect an EVM wallet (`WalletContext`) and use **Deposit USDC** / **Withdraw USDC** in `#portfolio` -> **Broker Account** (`DexBuilderTransferModal`).
3. **Trade** on `#event/<slug>` using **Market**, **Limit**, or **Smart Route** (atomic CLOB + LMSR AMM execution).
4. **Manage & Exit** from `#portfolio` with **TP +20%**, **Reverse** (one-tap YES/NO flip), or **Close**, then redeem winning shares at **$1.00 USDC** after resolution.

---

## Where to go next

- [Place an order](trading/place-order.md) — `Market`, `Limit`, `Smart Route`, Toxicity Shield, and TIF controls.
- [Market details](markets/market-details.md) — `Oracle Clarity` score, spread/slippage telemetry, and Community markets.
- [Positions](portfolio/positions.md) — `Cost Basis`, `TP +20%`, `Reverse`, and Portfolio tabs.
- [Collateral & Wallet](portfolio/collateral.md) — On-chain USDC `balanceOf`, EIP-712 signing, and DexBuilder Broker Account.
- [AGX Staking](agx-staking.md) — Tiers, fee discounts, and automated 24h reward epochs.
- [Pro Desks & Market Maker](pro-desks.md) — Copy trading and the multi-market GRG Fear & Greed Market Maker.
- [Resolution](resolution.md) — Optimistic oracle, deterministic feeds, and evidence proofs.
