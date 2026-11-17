# Resolution & Oracle (`#resolution`)

AlgoXen resolves markets through a bonded **optimistic oracle** (`app/services/settlement.py`) augmented with **pre-trade Oracle Clarity scoring** and **deterministic price/event feeds** (`app/services/oracle.py`).

---

## 1. Resolution Lifecycle

1. **Close Market** (`CLOSED`): Trading halts prior to proposal.
2. **Propose Outcome** (`IN_RESOLUTION`): An admin/oracle stakes a proposal bond (`$50` USDC) and asserts `proposed_outcome_index`, opening a **2-hour dispute window** (`DISPUTE_WINDOW`).
3. **Dispute** (`DISPUTED`, optional): Anyone posting a counter-bond `>= proposal bond` before `dispute_deadline` challenges the assertion.
4. **Finalize** (`RESOLVED`): Sets `winning_outcome_index` on the market and `FINALIZED` on `OracleDispute`. Winning shares redeem 1:1 for **`$1.00 USDC`** (`$0.00` for losing shares); AMM LPs can redeem their proportional pool + fee share (`POST /api/v4/prediction/amm/{market_id}/redeem`).

---

## 2. Deterministic Resolution Feeds (`POST /api/v4/prediction/resolution/resolve-feed`)

Instead of relying solely on manual proposals for objective price/event markets, admins/oracles can evaluate a deterministic feed:
- Supported providers: `gate:<PAIR>` (e.g., `gate:BTC_USDT`), `coingecko:<COIN_ID>`, and `static:<VALUE>` (for deterministic testing).
- Evaluates `observed_value <comparator> threshold` (`>=`, `>`, `<=`, `<`) -> outcome index `0` (`YES`) or `1` (`NO`).
- Persists verifiable proof JSON (`feed`, `observed_value`, `threshold`, `comparator`, `source_url`, `observed_at`) into `OracleDispute.evidence_json`.

---

## 3. Resolution UI (`ResolutionPage`)

Each card on `#resolution` (`frontend/src/pages/ResolutionPage.tsx`) displays:
- Event title, question, `StatusPill`, proposed winning outcome, proposer address, bond amount, and live dispute countdown.
- **`Oracle Proof / Evidence` box**: Displays attached `feed` comparison, `rationale`, and `source_url` from `evidence_json` so reviewers never rule-lawyer blind.
- **`Stake Counter-Bond & Dispute`** CTA while in `PROPOSED` state.
