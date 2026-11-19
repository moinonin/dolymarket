Found 4 CRITICAL, 4 HIGH, and
  3 MEDIUM loopholes/bugs.
  ──────
  ### 🔴 CRITICAL (Direct Financial / Resolution Exploits)
  1. Post-Expiry Trading & 30s Sniping Exploit
      • amm.py /dolymarket/app/services/amm.py#L221, orders.py /dolymarket/app/api/v4/orders.py#L197, settlement.py
      /dolymarket/app/services/settlement.py#L198
      • Only checks market.status == "ACTIVE", never checks Event.end_date <= now. Because resolution_worker_loop ticks every 30s, traders can buy
      winning shares from AMM/CLOB after end_date once outcome is known, draining LPs.
      • Fix: Reject trades/orders/splits with 409 whenever event.end_date <= now.
  2. AMM agx_fee Double-Counted in pool_usdc (Unbacked USDC Printing)
      • amm.py /dolymarket/app/services/amm.py#L271-L300
      • On BUY, pool.pool_usdc += total (full notional + fee). Then 50% of fee (agx_fee) is credited to AGX stakers/creators via record_fee, without
      deducting agx_fee from pool_usdc. Same fee gets paid twice (to AGX + to LPs on redeem).
      • Fix: Credit only notional + lp_fee to pool_usdc on BUY (deduct notional - lp_fee on SELL).
  3. Negative q_yes / q_no AMM Sell Exploit (redeem_lp Free Money Bug)
      • amm.py /dolymarket/app/services/amm.py#L273-L287 & amm.py /dolymarket/app/services/amm.py#L334-L345
      • A trader can split_position ($100 → 100 YES + 100 NO) and SELL 100 YES into an AMM with q_yes = 0 → pool.q_yes becomes -100. On resolution if
      YES wins, winning_liability = -100 → remaining_equity = pool_usdc - (-100) = pool_usdc + 100 → LP gets paid $100 more than exists in the pool!
      • Fix: Block AMM SELL when sh > pool.q_yes (or q_no), or clamp winning_liability = max(Decimal("0"), ...) and enforce non-negative pool
      inventory.
  4. Kalshi Verifier & Rule 3 (No data -> NO) Not Wired Into Endpoints/Worker
      • resolution.py /dolymarket/app/api/v4/resolution.py#L29-L79, resolution_worker.py /dolymarket/app/services/resolution_worker.py#L96-L176
      • POST /resolution/propose never passes source_url / evidence_text to settlement.propose_resolution(...) — bypassing oracle_verifier + Source
      Agency whitelist completely.
      • run_resolution_tick() only auto-proposes markets with oracle_feed. Qualitative Kalshi-rule markets with No data -> NO stay stuck in CLOSED
      forever because resolve_expired_no_data() is never called.
      • Fix: Forward source_url/evidence_text in /propose and wire resolve_expired_no_data() into resolution_worker.py.
  ──────
  ### 🟠 HIGH (Validation Bypasses, Races, DoS)

  5. PATCH /community/markets/{id} Bypasses Oracle Validation
      • community.py /dolymarket/app/api/v4/community.py#L244-L253 & community.py /dolymarket/app/api/v4/community.py#L336-L346
      • Missing validators on UpdateCommunityMarketRequest: allows NaN/Infinity in oracle_threshold, arbitrary strings in oracle_comparator, and
      mismatched oracle_feed without oracle_threshold (or vice versa).
      • Fix: Enforce identical validators + feed/threshold pairing on PATCH.
  6. Dispute Race Condition & Counter-Bond Underpayment (50 vs 100 AGX)
      • resolution.py /dolymarket/app/api/v4/resolution.py#L92-L106, settlement.py /dolymarket/app/services/settlement.py#L17 & settlement.py
      /dolymarket/app/services/settlement.py#L120-L151
      • dispute_proposal does NOT lock Market/OracleDispute with .with_for_update() → concurrent disputes can double-stake AGX.
      • PROPOSAL_BOND = 50, so a disputer can pass counter_bond=50 even though docs require 100 AGX.
      • Fix: Lock with .with_for_update(), stake AGX atomically, enforce MIN_DISPUTE_BOND = Decimal("100").
  7. OOM Crash via Unbounded Response in fetch_source_text
      • oracle_verifier.py /dolymarket/app/services/oracle_verifier.py#L50-L58
      • Downloads entire HTTP response body into RAM before slicing [:4000]. A large page/file OOM-kills a 500 MiB FastAPI Cloud Hobby instance. Also
      silently ignores socket.gaierror.
      • Fix: Stream with 64 KB hard cap (max_bytes=65536), verify text/* / application/json, reject unresolvable hosts.
  8. Permissionless Community Market Spam (Unfunded Sybil DoS)
      • community.py /dolymarket/app/api/v4/community.py#L128-L215
      • Any user can create unlimited UNFUNDED markets with $0 deposit and bond_with_agx=False, bloating DB + 30s worker scans.
      • Fix: Cap open UNFUNDED markets per user (e.g., max 5 active unfunded markets per creator).

  ──────
  ### 🟡 MEDIUM (Edge Cases & Hygiene)

  9. CreateCommunityMarketRequest._valid_future_end_date (community.py /dolymarket/app/api/v4/community.py#L71-L72): returns None instead of raising
  ValueError on a non-nullable str field.
  10. Substring Content Filter (markets.py /dolymarket/app/services/markets.py#L14-L27): "illegal" blocks legitimate political markets ("illegal
  immigration") while missing "murder"/"homicide". Use word-boundary rules.
  11. merge_positions Missing Status Check (settlement.py /dolymarket/app/services/settlement.py#L238-L266): does not reject EXPIRED markets.
  ──────


## Remediation Status (Verified)
- **#1 (CRITICAL) Post-Expiry Trading & 30s Sniping**: FIXED via `ensure_market_open_for_trading()` in `app/services/markets.py`, enforced across AMM (`amm.py`), CLOB + Smart Orders (`orders.py`), and CTF split (`settlement.py`). Covered by `test_vuln1_post_expiry_trading_blocked_across_amm_clob_smart_and_split`.
- **#2 (CRITICAL) AMM `agx_fee` Double-Counted in `pool_usdc`**: FIXED in `app/services/amm.py` (`BUY` credits `notional + lp_fee`; `SELL` deducts `notional - lp_fee`). Covered by `test_vuln2_amm_pool_usdc_does_not_double_count_agx_fee`.
- **#3 (CRITICAL) Negative `q_yes`/`q_no` AMM Sell Exploit**: FIXED in `app/services/amm.py` (blocks selling more shares than `pool.q_yes`/`pool.q_no` issued + clamps `winning_liability >= 0` in `redeem_lp`). Covered by `test_vuln3_amm_blocks_selling_more_shares_than_pool_issued`.
- **#4 (CRITICAL) Kalshi Verifier & Rule 3 Not Wired**: FIXED in `app/api/v4/resolution.py` (`/propose` forwards `source_url`/`evidence_text`) and `app/services/resolution_worker.py` (Step 2b auto-proposes `NO` via `resolve_expired_no_data()`). Covered by `test_vuln4_propose_enforces_kalshi_whitelist_and_worker_applies_rule3`.
- **#5 (HIGH) `PATCH /community/markets/{id}` Oracle Bypass**: FIXED in `app/api/v4/community.py` (finite threshold, comparator allowlist, feed/threshold pairing). Covered by `test_vuln5_patch_community_market_validates_oracle_fields`.
- **#6 (HIGH) Dispute Race & 100 AGX Counter-Bond Floor**: FIXED in `app/services/settlement.py` (`with_for_update()` on `Market` + `OracleDispute`, `MIN_DISPUTE_BOND = Decimal("100")`). Covered by `test_vuln6_dispute_enforces_100_agx_minimum_bond`.
- **#7 (HIGH) Unbounded HTTP Response OOM in `fetch_source_text`**: FIXED in `app/services/oracle_verifier.py` (64 KB streaming byte cap + text/JSON/XML Content-Type allowlist). Covered by `test_vuln7_fetch_source_text_caps_bytes_and_rejects_binary`.
- **#8 (HIGH) Unfunded Community Market Spam DoS**: FIXED in `app/api/v4/community.py` (`MAX_UNFUNDED_MARKETS_PER_USER = 5`, returns `429`). Covered by `test_vuln8_unfunded_community_market_spam_capped`.
- **#9 (MEDIUM) `_valid_future_end_date` Returns `None`**: FIXED in `app/api/v4/community.py` (raises `ValueError`).
- **#11 (MEDIUM) `merge_positions` Missing Status Guard**: FIXED in `app/services/settlement.py` (rejects `EXPIRED`/`UNFUNDED` with `409`). Covered by `test_vuln11_merge_positions_rejected_on_expired_market`.
- **#10 (MEDIUM) Content Filter Refinement**: Deferred (non-blocking).
