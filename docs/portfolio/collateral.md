# Collateral & Web3 Wallet

AlgoXen supports **simulation USDC collateral** as well as **non-custodial EVM wallet connections**.

---

## 1. Web3 Wallet Connection

Click **Connect Wallet** in the top navigation to link MetaMask, Rabby, Coinbase Wallet, Gate Wallet, or another EVM browser wallet:
- **On-Chain USDC Balance**: Displays your wallet's USDC balance across Ethereum, Optimism, Polygon, Base, Arbitrum One, and Base Sepolia.
- **Non-Custodial Signing**: Sign in or authorize wallet transfers directly inside your browser wallet extension.

---

## 2. Broker Account (`Portfolio → Broker Account`)

When your EVM wallet is connected and linked, the **Broker Account** tab shows:
- Live **Wallet USDC** balance.
- **Deposit USDC** / **Withdraw USDC** flows signed directly in your wallet with clickable block-explorer links.
- **Claim all** for settled winnings.

---

## 3. Simulation Collateral (`Portfolio`)

In simulation mode:
- **Deposit** adds virtual USDC (up to `$100,000` per deposit) for trading and funding Community Markets.
- **Withdraw** removes available (unlocked) virtual USDC.
- **Order Locks**: Buying locks `price × amount` USDC; selling locks shares. Locks release automatically when orders fill or are cancelled.
