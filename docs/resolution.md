# Resolution & Oracle

AlgoXen resolves markets through **deterministic primary feeds**, **Kalshi-style 3-clause market rules**, and an **offline neuro-symbolic verifier (`oracle-s1`)** backed by a 2-hour optimistic dispute window.

---

## 1. Standardized Market Rules (3-Clause Contract)

Every qualitative or event-driven market follows a strict 3-clause rule structure adapted from Kalshi's exchange rulebook:

1. **Declarative Resolution Condition (`Resolves Yes if ...`)**
   - Each market defines a single, verifiable statement with an exact target threshold (when numeric) and UTC cutoff date.
   - Example: *"Resolves Yes if Take-Two Interactive Software, Inc. (including Rockstar Games) publicly reports before January 1, 2027 that Grand Theft Auto VI has reached at least 36 million units sold-in."*
2. **Approved Source Agencies (`Outcome verified from ...`)**
   - Each market lists the exact primary news wires, government agencies, or official investor-relations portals permitted as proof (for example: Reuters, Associated Press, BBC, The Wall Street Journal, Bloomberg News, CNBC, CBS, NBC, ABC, Fox News, The Washington Post, CNN, The New York Times, SEC, BLS, Federal Reserve, or the issuer's official IR portal).
   - **Automatic domain enforcement:** Any submitted `source_url` outside the market's approved Source Agency domains is rejected immediately (`HTTP 422`) before evidence evaluation runs. Unverified blogs, social media rumors, and private URLs cannot trigger resolution.
3. **Expiration Default (`No data -> NO`)**
   - If no approved Source Agency publishes data confirming the `Resolves Yes if` condition by the market's Expiration Date, the market resolves deterministically to **`NO`** (`confidence = 1.0`).
   - If a market explicitly lists a `"No data"` strike, the `"No data"` strike resolves **`YES`** and all other strikes resolve **`NO`**.

---

## 2. How AlgoXen Differs from Kalshi

AlgoXen adopts Kalshi's 3-clause rulebook for clarity and source integrity, with four explicit operational differences:

| Dimension | Kalshi | AlgoXen |
|---|---|---|
| **Rule structure** | Declarative `Resolves Yes if`, Source Agencies, no-data defaults to `NO` | **Identical 3-clause contract** parsed and enforced directly in code |
| **Quantitative feeds** | Manual / scheduled exchange settlement | **Automated deterministic adapters** (`gate:`, `coingecko:`, `fred:`, `stooq:`, `nws:`) attach raw API observations, thresholds, and timestamps automatically |
| **Qualitative verification** | Internal exchange resolution committee | **Automated offline `oracle-s1` verifier** (Source Agency domain whitelist + deterministic clock & numeric threshold guard + quantized ONNX NLI cross-encoder) |
| **Dispute mechanism** | Internal exchange review (no public trader bond) | **2-hour optimistic challenge window**: any signed-in trader can dispute with a **100 AGX** counter-bond (+20% AGX reward if upheld) |
| **Settlement asset** | Real USD (CFTC-regulated DCM) | Simulated USDC / CTF outcome shares (`$1.00` winning redemption, `$0.00` losing) |

---

## 3. Resolution Lifecycle

1. **Close Market (`CLOSED`)**: When a market's end time passes, trading closes automatically and resting open limit orders are cancelled with locked collateral released.
2. **Propose Outcome (`IN_RESOLUTION`)**:
   - **Feed markets** evaluate the closing observation from the attached provider (`observed_value <comparator> threshold`) and propose the winning outcome automatically.
   - **Qualitative markets** validate the submitted `source_url` against approved Source Agencies, check any numeric threshold deterministically, and verify entailment via `oracle-s1`. Contradictory or non-whitelisted submissions are rejected (`HTTP 422`).
   - **Expired markets with no Source Agency data** resolve deterministically to **`NO`**.
   - Every valid proposal opens a **2-hour dispute window**.
3. **Dispute (`DISPUTED`, optional)**: During the 2-hour window, any signed-in trader can challenge a proposed outcome by staking a **100 AGX counter-bond** on the **Resolution** page. Disputed markets pause for review; if the dispute is upheld, the 100 AGX stake is returned plus a **20% AGX reward**.
   - **Single Re-Proposal (`REPROPOSED`)**: After a first dispute, an operator may issue one corrected re-proposal (`POST /api/v4/prediction/resolution/repropose`), opening a fresh 2-hour challenge window. If disputed a second time, no further re-proposal is permitted and the market must be finalized directly.
   - **Immutable `rules_hash` & Audit Trail**: Every market exposes a deterministic SHA-256 `rules_hash` (locked once funded) and an append-only `updates[]` timeline (`PROPOSED → DISPUTED → REPROPOSED → FINALIZED`).
4. **Finalize (`RESOLVED`)**: Uncontested proposals finalize automatically once the 2-hour window expires. Winning shares redeem 1:1 for **$1.00 USDC** (`$0.00` for losing shares), and AMM liquidity providers can claim their pool share via **Redeem LP**.
   - **Cancelled / Ambiguous 50-50 Settlement (`INVALID`)**: If an event is cancelled, postponed indefinitely, or cannot be resolved cleanly, finalization with `resolve_invalid=true` (`winning_outcome_index = -1`) pays **$0.50 USDC** per YES share and **$0.50 USDC** per NO share, with AMM LP equity computed against the exact 50/50 liability.

---

## 4. Automated Deterministic Feeds

Markets can attach a primary data feed at creation:

- **Crypto**: `gate:<PAIR>` (e.g. `gate:BTC_USDT`), `coingecko:<COIN_ID>` (e.g. `coingecko:bitcoin`)
- **Macro / Rates**: `fred:<SERIES_ID>` (e.g. `fred:FEDFUNDS`, `fred:CPIAUCSL`)
- **Equities & Indices**: `stooq:<SYMBOL>` (e.g. `stooq:^spx`)
- **Weather**: `nws:<STATION>:<F|C>` (e.g. `nws:KNYC:F`)
- **Rule format**: `observed_value <comparator> threshold` (`>=`, `>`, `<=`, `<`, `==`) resolves `YES` or `NO`.
- Every automated proposal attaches verifiable proof (feed name, observed value, threshold, source URL, and timestamp) directly on the **Resolution** page.

---

## 5. Resolution Page

Visit **Resolution** in the top navigation to view:
- Markets currently in their 2-hour challenge window or under dispute.
- Proposed winning outcome, bond details (`100 AGX` to dispute), and live countdown timer.
- **Oracle Proof / Evidence** showing the exact feed observation or approved Source Agency citation.
- **Stake 100 AGX Counter-Bond & Dispute** button while a proposal is active.
