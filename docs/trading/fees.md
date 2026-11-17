# Fees

```
Fee = C × feeRate × p × (1 − p)
```

- `C` — trade size in shares.
- `feeRate` — category rate (Politics 1.5%, Crypto 2.0%, Sports 2.5%, Macro 1.0%, Pop Culture 2.0%, Tech 1.5%).
- `p` — trade price.

Fees peak at a 50/50 probability and approach zero near `0.01` or `0.99`. Both makers and takers pay the parabolic fee on order-book fills; AGX stakers receive a **5%–15% taker-fee discount**. AMM pool trades charge a flat **1%** fee split 50/50 between liquidity providers and the AGX fee pool.
