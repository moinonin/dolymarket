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

## Review and audit

A desk becomes visible in the leaderboard only after an admin approves it.

- **Review queue** — the console (`#/admin`, admin accounts only) lists the desks
  waiting for review with their owner email and follower count, and can approve,
  reject (with a reason) or suspend them. The queue is also available as
  `GET /api/v4/prediction/admin/desks` (`status` defaults to `PENDING_REVIEW`).
- **Copy activity** — every mirrored order is recorded as a copy job with the
  requested and filled size. Traders see their own jobs under **Activity**
  (`GET /api/v1/copy-jobs`); admins see every account's jobs in the console
  (`GET /api/v4/prediction/admin/copy-jobs`).

Every route under `/api/v4/prediction/admin/*` answers HTTP 403
`ADMIN_REQUIRED` for a regular account.