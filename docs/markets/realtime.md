# Real-time data

Public WebSocket: `/api/v4/prediction/ws/public` — depth, BBO, trades.
Private WebSocket: `/api/v4/prediction/ws/private?token=...` — your fills and
order updates.
Upstream live stream: `/api/v4/prediction/live/ws` — bridges the DexBuilder
broker (depth, BBO, trades, status) into the local envelope so the live market
page can stream without polling. The browser never connects to the upstream
broker; the server owns the upstream protocol. See
[Live DexBuilder data](../live-data.md#live-streaming).

Client policy: exponential backoff (1s to 30s, jitter 0-20%), heartbeat every
30s, resync order book snapshot on reconnect.