# Order lifecycle

```
OPEN  ->  PARTIALLY_FILLED  ->  FILLED
  |            |                   |
  +-> CANCELLED (IOC remainder / manual cancel)
  +-> REJECTED  (validation failure)
```

- **OPEN** — resting in the book.
- **PARTIALLY_FILLED** — some shares filled, remainder resting.
- **FILLED** — fully executed.
- **CANCELLED** — cancelled by you or by an IOC/FOK remainder.
- **REJECTED** — failed validation (price, size, balance, self-trade).

## Cancelling
Cancel one order (`DELETE /orders/{id}`) or batch-cancel by market/condition
(`DELETE /orders`).

## Idempotency
Send `X-Idempotency-Key` on `POST /orders` to safely retry network failures.
A retried key with the same payload replays the cached response; a different
payload returns 409.