# Roles and permissions

| Role | Can do |
|---|---|
| **Visitor** | Read markets, books, tickers, public WebSocket streams. |
| **Trader** | Deposit/withdraw, submit/cancel orders, view own positions/trades, claim payouts, follow Pro Desks. |
| **Operator** | Everything a trader does, plus own a Pro Desk and tag orders with it. |
| **Admin** | Everything above, plus create events/markets, close markets, review desks. |

## Ownership rules
- You can view, cancel or redeem **only your own** orders, positions and trades.
- Requests for another user's resource are rejected with **403** (or 404) without
  disclosing that it exists.
- Unauthenticated requests to private endpoints return **401**.

## Algorithmic traders
Use an HMAC-signed API key (`X-API-KEY`, `X-TIMESTAMP`, `X-SIGNATURE`) instead
of a JWT. Signatures are HMAC-SHA256 over `TIMESTAMP + METHOD + PATH + BODY`.