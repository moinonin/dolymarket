# FAQ

**Is this real money?** No. AlgoXen currently runs in a simulation environment with virtual USDC balances.

**Can I lose money?** Simulated USDC only; no real funds are at risk.

**How are markets resolved?** Deterministic feeds (`gate:`, `coingecko:`, `fred:`, `stooq:`, `nws:`) evaluate automatically at close. Qualitative markets follow Kalshi-style 3-clause rules (declarative `Resolves Yes if`, approved Source Agency domain whitelist, and `No data -> NO` at expiration) verified by our offline `oracle-s1` engine. Every proposal opens a 2-hour dispute window (100 AGX counter-bond); uncontested proposals finalize automatically and pay **$1.00 USDC** per winning share.

**Can I create my own market?** Yes — go to **Live Markets → Community** and click **Create Community Market**. Every market requires a future UTC `end_date`, binary `Will ...?` framing, and objective resolution criteria (checked live by the Oracle Clarity Gauge while you type). Markets activate once funded with at least **$10 USDC** in LP liquidity (or auto-refund LPs if they expire unfunded).

**What is a Pro Desk?** A public track record you can follow; fills are mirrored proportionally into your own account.

**Is copy trading custodial?** No. Your own collateral funds every copy order.
