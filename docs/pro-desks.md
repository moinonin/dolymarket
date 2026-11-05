# Pro Desks (copy trading)

A **Pro Desk** is a public track record owned by one operator. The desk trades
only with the operator's own collateral. Followers opt in with a **copy ratio**
and mirror the desk's fills proportionally into their own accounts.

- Non-custodial: no pooled money, no vault share, no NAV, no redemption.
- No fee tied to trading results.
- Track record is deterministic (ROI, win rate, max drawdown) and computed from
  stored fills and settled positions.
- Anti front-running: an operator may not place a personal order in a market
  where their desk holds a position.

See `docs/prediction-vault-prompt.md` for the full contract.