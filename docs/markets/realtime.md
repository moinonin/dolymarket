# Real-time data

Public WebSocket: `/api/v4/prediction/ws/public` — depth, BBO, trades.
Private WebSocket: `/api/v4/prediction/ws/private?token=...` — your fills and
order updates.

Client policy: exponential backoff (1s to 30s, jitter 0-20%), heartbeat every
30s, resync order book snapshot on reconnect.