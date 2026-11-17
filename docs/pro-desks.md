# Pro Desks, Copy Trading & GRG Market Maker (`#desks`)

A **Pro Desk** is a public track record owned by one operator trading their own collateral (`app/api/v1/desks.py`, `app/services/copy_engine.py`).

---

## 1. Non-Custodial Copy Trading

- **No pooled funds**: No vault share, no NAV, no custody transfer. Followers opt in with a `copy_ratio` and mirror the desk's fills proportionally into their own accounts.
- **Risk Caps**: Followers configure per-market USDC caps (`per_market_cap_usdc`, default `$50`), max per-market equity %, and max total copy exposure %.
- **Anti front-running**: Desk operators cannot place personal orders in a market where their desk holds an open position (`409 DESK_MARKET_CONFLICT`).
- **Deterministic Track Record**: ROI, net PnL, win rate, and max drawdown are computed from stored fills and settled positions (`app/services/desk_track_record.py`).
- **Gating**: Creating/activating a Pro Desk binds the complementary **500 AGX** desk bond if available (`ensure_desk_bond`, released on archive via `release_desk_gating`).

---

## 2. Multi-Market GRG Fear & Greed Market Maker (`DeskMarketMakerPanel`)

Mounted on `DeskDetailPage` (`#desks/<id>`), `DeskMarketMakerPanel` (`frontend/src/components/DeskMarketMakerPanel.tsx`) controls automated two-sided `post_only` quoting (`app/services/market_maker.py`):

### Strategy & Quoting (`compute_quotes`)
- Consumes 10s microstructure readings from `fear_greed_service` (`score_0_100`, `v_alpha`, `ewi`, `regime_state`).
- Adjusts fair value for sentiment/velocity (`k_fg`, `k_vel`, optional `crypto_skew`) and applies inventory skew (`gamma`), quantizing bid/ask to market `tick_size`.
- **Multi-Market per Desk**: Keyed on `(desk_id, token_id)` so one desk quotes multiple markets concurrently and auto-resumes on server boot.

### 5 Hard Circuit Breakers
1. **EWI Toxicity Halt**: Pulls all resting quotes when `ewi >= 0.75` (`ewi_critical`) or `early_warning` triggers; resumes with hysteresis at `ewi <= 0.55`.
2. **Pre-Expiry Pull**: Halts `N` minutes (`15` default) before `Event.end_date`.
3. **Local Midpoint-Jump Guard**: Halts on sudden local book jumps (`>= $0.08/tick`).
4. **Per-Market Capital & Loss Caps**: Enforces `max_usdc_exposure` (`$500` default), `max_inventory`, and `daily_loss_limit_usdc` (`$50` default).
5. **Desk Portfolio-Wide Exposure Cap**: Enforces `desk_max_total_exposure_usdc` (`$2,000` default) across all `DeskPosition` rows for the desk (`DESK_TOTAL_EXPOSURE_CAP`).

---

## 3. Review & Audit

- **Admin Approval (`#admin`)**: Desks start in `DRAFT` -> `PENDING_REVIEW` and appear on `#desks` after admin approval (`POST /api/v4/prediction/admin/desks/{id}/approve`).
- **Copy Activity (`#copy`)**: Traders inspect their mirrored orders in `CopyActivityPage` (`GET /api/v1/copy-jobs`); admins audit all copy jobs in `#admin`.
