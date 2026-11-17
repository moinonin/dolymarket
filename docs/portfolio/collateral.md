# Collateral, Web3 Wallet & On-Chain Transfers

Dolymarket supports both **local simulation collateral** and **non-custodial on-chain USDC deposits/withdrawals** via the connected EVM wallet (`WalletContext.tsx`) and DexBuilder Broker API.

---

## 1. Web3 Wallet Connection (`WalletButton` & `WalletConnectModal`)

`frontend/src/context/WalletContext.tsx` manages browser wallet connections:
- **Multi-Wallet Discovery**: Uses **EIP-6963** (`eip6963:announceProvider`) to discover MetaMask, Rabby, Coinbase Wallet, Gate Wallet, etc., with `window.ethereum` / `window.gatewallet` fallback.
- **Hung-Shim Guard**: A 20-second timeout prevents UI lockups if a browser extension shim stalls (for example, Gate Wallet colliding with another Cardano wallet locking `window.cardano`).
- **On-Chain USDC Balance (`viem`)**: Queries ERC-20 `balanceOf(address)` (`6` decimals) via `eth_call` across:
  - Ethereum (`1`), Optimism (`10`), Polygon (`137`), Base (`8453`), Arbitrum One (`42161`), and Base Sepolia (`84532`).
  - Displayed in `WalletButton` dropdown, `CashLedgerModal`, `DexBuilderBrokerPanel`, and `DexBuilderTransferModal` with manual refresh.

---

## 2. On-Chain Deposit & Withdraw Signing (`#portfolio` -> Broker Account)

In `DexBuilderBrokerPanel` (`frontend/src/components/DexBuilderBrokerPanel.tsx`), users with a bound DexBuilder wallet see:
- **Live `Wallet USDC`** balance badge.
- **`Deposit USDC`** / **`Withdraw USDC`** buttons opening `DexBuilderTransferModal`:
  - **Deposit Flow**: Calls `POST /api/v4/dexbuilder/platform/deposit/sign_data` and executes `eth_sendTransaction`, `eth_signTypedData_v4` (EIP-712), or `personal_sign` in the connected wallet. Prevents overdrawing below on-chain USDC balance.
  - **Withdraw Flow**: Calls `POST /api/v4/dexbuilder/platform/withdraw/sign_data`, requests EIP-712 / message signature from the wallet, and posts the signed payload to `POST /api/v4/dexbuilder/platform/withdraw/submit`.
- **Non-Custodial Transparency**: Every deposit and withdrawal card displays a status pill, `nonce`, and a clickable block-explorer transaction link (`Basescan`, `Etherscan`, `Arbiscan`, `Polygonscan`, or `Optimistic Etherscan`) based on chain ID.
- **`Claim all`**: Claims available DexBuilder winnings (`POST /api/v4/dexbuilder/claims`).

---

## 3. Simulation Collateral (`CashLedgerModal`)

For local CLOB/AMM testing (`ENABLE_DEMO_COLLATERAL=1`, default in dev/test):
- **Deposit** (`POST /api/v1/collateral/deposit`): Credits simulated USDC (`<= $100,000` per request, supports `Idempotency-Key` deduplication). Automatically disabled (`403 DEMO_COLLATERAL_DISABLED`) when `APP_ENV=production` or `ENABLE_DEMO_COLLATERAL=0`.
- **Withdraw** (`POST /api/v1/collateral/withdraw`): Removes available (`balance - locked_balance`) USDC.
- **Locks**: Buy orders lock `price × amount` USDC; sell orders lock shares. Locks release automatically on cancel or fill, and `select ... FOR UPDATE` serializes balance updates on Postgres.
