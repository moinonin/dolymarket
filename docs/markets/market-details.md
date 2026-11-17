# Market Details, Community Markets & AMM

AlgoXen surfaces two complementary market views: **Live Markets** (real-time global order books) and **Community / Local Markets** (**Live Markets → Community**).

---

## 1. Community Markets

Any signed-in user can launch a binary (`YES` / `NO`) prediction market from **Live Markets → Community → Create Community Market**:

- **Activation Threshold (`$10 USDC`)**: Markets start as `UNFUNDED` until at least `$10 USDC` in LP liquidity is deposited, at which point they transition to `ACTIVE` and open for trading.
- **Unfunded Expiry**: If a market's end date passes while still `UNFUNDED`, it automatically transitions to `EXPIRED` and refunds partial LP deposits pro rata.
- **Automated Price Oracle (Optional)**: Attach a live feed (`gate:BTC_USDT` or `coingecko:bitcoin`), comparator (`>=`, `>`, `<=`, `<`), and threshold so the market closes and proposes its winning outcome automatically at expiry.

---

## 2. Oracle Clarity Score

Every local/community market displays a **0–100 Oracle Clarity** badge (`HIGH >= 75`, `MEDIUM >= 50`, `LOW < 50`) based on 4 criteria (25 points each):

1. **Authoritative Source**: Cites a verifiable price feed or data source.
2. **Numeric / Binary Predicate**: States an unambiguous threshold or condition.
3. **Explicit UTC Deadline**: Specifies when the outcome is evaluated.
4. **Objective Language**: Clear, non-subjective resolution wording.

---

## 3. Market Detail & Hybrid LMSR AMM Pool

From any event page, click **AMM & LP Pool →** to inspect:
- **Liquidity Metrics**: Best bid-ask spread, `$100` buy slippage estimate, and market health.
- **Deposit LP**: Add USDC liquidity to the market's LMSR pool to deepen liquidity and earn 50% of AMM trading fees.
- **Instant AMM Trade**: Quote and execute immediate `BUY` / `SELL` fills directly against the AMM pool.
- **Redeem LP**: Claim your proportional pool equity + accumulated fees once the market is `RESOLVED`.
