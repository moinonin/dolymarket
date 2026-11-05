# Place an order

## Order types
- **LIMIT** — rests at your price until filled or cancelled.
- **MARKET** — fills immediately at the best available price.

## Sides
- **BUY** — acquire outcome shares; locks `price × amount` USDC.
- **SELL** — dispose of shares; locks shares.

## Time in force
- **GTC** — good till cancelled (default).
- **IOC** — immediate or cancel: fill what you can, cancel the rest.
- **FOK** — fill or kill: fill the whole amount or cancel entirely.

## Post-only
Guarantees you are a maker (never cross the spread). Rejected if it would
cross.

## Self-trade prevention
An order that would match your own resting order is rejected.

## Minimums
Orders must be at least `min_order_size` shares and prices must be a multiple of
the tick size.