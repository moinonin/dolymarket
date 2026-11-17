# Order lifecycle

```
OPEN  ->  PARTIALLY_FILLED  ->  FILLED
  |            |                   |
  +-> CANCELLED (IOC/FOK remainder, manual cancel, or market close)
  +-> REJECTED  (validation failure)
```

- **OPEN** — resting in the order book.
- **PARTIALLY_FILLED** — some shares filled, remainder resting.
- **FILLED** — fully executed.
- **CANCELLED** — cancelled manually, by an IOC/FOK remainder, or automatically when a market closes.
- **REJECTED** — failed validation (price, size, available balance, or self-trade).

## Cancelling Orders
Cancel individual resting orders or batch-cancel open orders from the **Orders** tab in **Portfolio**. Locked USDC or shares are released immediately upon cancellation.
