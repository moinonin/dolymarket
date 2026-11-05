# Positions

A position is your net share balance in a token. Fields:
- `shares` — net shares held.
- `locked_shares` — shares reserved by open sell orders.
- `avg_entry_price` — volume-weighted average entry.
- `realized_pnl` — realized profit/loss from sells.

Positions update on every fill and are user-scoped (403 on foreign access).