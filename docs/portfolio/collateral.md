# Collateral

- **Deposit** — add USDC to your account (simulation).
- **Withdraw** — remove available (unlocked) USDC.
- **Available** = `balance - locked_balance`.
- **Locked** — reserved by open buy (USDC) and sell (shares) orders.

Locks release automatically on cancel or fill. Fees are charged from the
unlocked balance.