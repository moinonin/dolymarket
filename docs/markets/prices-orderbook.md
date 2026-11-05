# Prices and order book

- **Best bid / best ask** — tightest resting prices.
- **Mid** — `(bid + ask) / 2`.
- **Spread** — `ask - bid`.
- **Depth** — resting size at each price level (L2 snapshot).
- **Last trade price** — most recent fill.

Order books stream over WebSocket and resync from a REST snapshot on reconnect.