# Fees

```
Fee = C × feeRate × p × (1 − p)
```

- `C` — trade size in shares.
- `feeRate` — category rate (Politics 1.5%, Crypto 2.0%, Sports 2.5%, Macro
  1.0%, Pop Culture 2.0%, Tech 1.5%).
- `p` — price of the trade.

Fees peak at a 50/50 probability and vanish near 0 or 1. Makers and takers
both pay; post-only orders guarantee maker status. Fees are charged in USDC
from the unlocked balance.