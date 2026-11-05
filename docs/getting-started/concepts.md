# Concepts

## Event
A real-world question with a resolution date, e.g. "Will X win the election?".
An event groups one or more markets.

## Market
A tradable question with a fixed set of outcomes. Each market has a
**tick size** (minimum price increment, usually 0.01) and a **minimum order
size**.

## Outcome token
One share of one outcome. A winning token redeems at **$1.00**; a losing token
at **$0.00**. Prices are probabilities: a YES token at 0.62 implies a 62%
chance.

## Price
Prices live between 0.01 and 0.99 and must be a multiple of the tick size.
`Fee = C × feeRate × p × (1 − p)` — cheapest near certainty, most expensive
at a coin flip.

## Order book (CLOB)
Resting limit orders sorted by price-time priority. Bids descend, asks
ascend. The engine matches aggressive orders against resting liquidity in
memory and persists fills with monotonic sequence ids.

## Collateral
USDC deposited into your account. Buying locks `price × amount`; selling locks
shares. Locks are released on cancel or fill.

## Conditional tokens (CTF)
Outcome shares are minted by splitting USDC (`split`) and burned by merging
(`merge`) or redeeming (`redeem`) after resolution.

## Negative risk
Some markets (e.g. multi-outcome) use negative-risk accounting so that
buying one outcome implicitly shorts the others.