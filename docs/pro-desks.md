# Pro Desks & Copy Trading

A **Pro Desk** is a public track record owned by one operator trading their own collateral.

---

## 1. Non-Custodial Copy Trading

- **No pooled funds**: There is no custody transfer or pooled vault. Followers choose a `copy_ratio` and mirror the desk's fills proportionally into their own accounts.
- **Risk Caps**: Followers configure per-market USDC caps (`$50` default), max per-market equity %, and max total copy exposure %.
- **Anti Front-Running**: Desk operators cannot place personal orders in a market where their desk already holds an open position.
- **Deterministic Track Record**: ROI, net PnL, win rate, and max drawdown are calculated directly from verified fills and settled positions.
- **Desk Bond**: Activating a Pro Desk locks a **500 AGX** bond (when AGX is held), released if the desk is archived.

---

## 2. Automated Market Making

Desk operators can enable automated two-sided `post_only` quoting on individual markets from a desk's detail page, protected by 5 built-in circuit breakers:
1. **Volatility / Toxicity Halt**: Automatically pulls quotes during elevated market stress and resumes once conditions stabilize.
2. **Pre-Expiry Pull**: Halts quoting shortly before a market's end date.
3. **Midpoint-Jump Guard**: Halts on sudden sharp price jumps.
4. **Per-Market Capital & Loss Caps**: Enforces per-market exposure, inventory, and daily loss limits.
5. **Desk Portfolio Exposure Cap**: Caps total exposure across all markets traded by the desk.

---

## 3. Tracking Copy Activity

Switch to **Desks → Copy Activity** to inspect your mirrored copy-trading executions and risk-cap status in real time.
