# ALGOXEN Prediction Market Integration Specification

Version 1.0 — Architecture & Implementation Reference

## 1. Executive Summary & Purpose

This document defines the formal product, architecture, smart contract, backend, and economic specification for integrating a **Prediction Market Protocol** into the **ALGOXEN** ecosystem on Arbitrum One.

### 1.1 Context & Strategic Opportunity

Leading prediction market platforms (e.g., Polymarket, Kalshi) rely heavily on centralized listing processes:
- **Polymarket**: Requires manual proposal submission, editorial review, and centralized listing approval. End users cannot permissionlessly deploy arbitrary prediction markets.
- **Kalshi**: Operates under direct regulatory (CFTC) oversight with institutional review, restricting creation strictly to approved contracts.

**ALGOXEN's Strategic Edge**:
ALGOXEN is building the unified tokenized allocation layer for on-chain quantitative markets. By introducing a **hybrid prediction market architecture** combining:
1. **Permissionless Community Markets**: Open creation protocol where any user can define questions, collateralize initial liquidity, and earn trading fees.
2. **Official ALGOXEN Curated Markets**: Benchmark macro, crypto, and quantitative event markets seeded with native ALGOXEN liquidity and treasury backing.

This model scales market breadth organically without committing ALGOXEN treasury capital to unvetted long-tail markets, while funneling protocol trading fees into the AGX ecosystem and reward engine.

---

## 2. Core Architecture & Market Dichotomy

The protocol operates a two-tiered structure separating community-driven permissionless markets from protocol-seeded benchmark markets:

```
+-----------------------------------------------------------------------------------+
|                             ALGOXEN PROTOCOL SUITE                                |
+-----------------------------------------------------------------------------------+
           |                                                       |
           v                                                       v
+-----------------------------+                         +-----------------------------+
|    COMMUNITY MARKETS        |                         |   OFFICIAL ALGOXEN MARKETS  |
|  (Permissionless Creation)  |                         |    (Curated / Benchmark)    |
+-----------------------------+                         +-----------------------------+
| - Anyone can create         |                         | - ALGOXEN Treasury deploy   |
| - Creator provides min pool |                         | - Native ALGOXEN liquidity  |
| - Creator defines criteria  |                         | - Verified oracle feeds     |
| - Creator fee incentive     |                         | - Zero spam / high volume   |
| - Zero ALGOXEN treasury risk|                         | - Treasury PnL / fee driver |
+-----------------------------+                         +-----------------------------+
           \                                                       /
            \                                                     /
             v                                                   v
+-----------------------------------------------------------------------------------+
|                 UNIFIED TRADING ENGINE & RESOLUTION FRAMEWORK                     |
|     - Arbitrum One EVM (USDC Collateral Base)                                     |
|     - Conditional Tokens (ERC-1155 Binary / Categorical Shares)                   |
|     - Dynamic AMM / Hybrid Orderbook Router                                       |
|     - Optimistic Oracle & Multi-stage Dispute Module                              |
|     - Protocol Fee Router -> AGX Staking Rewards & Treasury                       |
+-----------------------------------------------------------------------------------+
```

### 2.1 Comparative Operating Model

| Feature | Permissionless Community Markets | Official ALGOXEN Markets |
| :--- | :--- | :--- |
| **Market Creator** | Any connected Web3 wallet / 3rd party | ALGOXEN Protocol Governance / Multi-sig |
| **Listing Gate** | Minimum initial liquidity deposit & anti-spam bond | Protocol curation & internal verification |
| **Initial Liquidity** | Provided entirely by creator / community | Seeded by ALGOXEN Treasury / Designated LP |
| **Tradability Status** | Inactive until Minimum Liquidity Threshold met | Instantly tradable upon contract activation |
| **Fee Economics** | Creator fee share (30-50%) + Protocol fee share | 100% protocol fees to Treasury & AGX Stakers |
| **Resolution Framework** | Standardized oracle template (UMA / Pyth / Multi-sig fallback) | Standardized verified oracle or multi-sig consensus |
| **ALGOXEN Capital Exposure** | **Zero** (no protocol treasury exposure) | **Active** (treasury capital utilized for depth) |

---

## 3. Key Architectural Pillars

To ensure market integrity and prevent the failure modes common to permissionless prediction platforms, the system implements three mandatory safeguards:

### 3.1 Minimum Liquidity & Anti-Spam Gate
- **Problem**: Completely free creation creates thousands of zombie, duplicate, or uncollateralized markets.
- **Specification**:
  - Anyone may deploy a market specification draft on-chain.
  - The market remains in a `PENDING_LIQUIDITY` state and is **not tradable** on the public interface until a configurable **Minimum Initial Liquidity** (e.g., 500 USDC) is deposited into the market pool.
  - A refundable **Creator Bond** (e.g., 50 USDC or equivalent AGX) is locked until market expiry and clean resolution. If the creator provides an ambiguous, malicious, or unverifiable resolution criterion that is rejected, the bond is slashed.

### 3.2 Immutable, Standardized Resolution Rules
- **Problem**: Malicious creators write ambiguous questions or alter resolution criteria post-launch to rug participants.
- **Specification**:
  - Resolution rules, target dates, and designated oracle feeds are **strictly immutable** once the market contract is initialized.
  - Standardized resolution schemas enforce:
    1. Exact determination timestamp (e.g., Unix timestamp UTC).
    2. Primary data source URL / API / on-chain oracle identifier.
    3. Fallback resolution source in case the primary data source is offline.
    4. Explicit tie / invalidity handling (e.g., 50-50 split or full collateral refund).

### 3.3 Creator Fee Revenue Sharing
- **Problem**: Lack of economic incentive for creators to curate high-quality questions and bring outside trading volume.
- **Specification**:
  - A fixed trading fee (e.g., 1.00% - 2.00%) is collected on all share mints, swaps, and redemptions.
  - Fee split:
    - **Market Creator**: 40% of collected trading fees (claimable continuously in USDC).
    - **ALGOXEN Protocol**: 60% of collected trading fees (routed to `RewardClaims.sol` for AGX stakers and treasury reserves).

---

## 4. Market Lifecycle

Every prediction market on ALGOXEN moves through a deterministic state machine:

```
[ CREATED ] 
     |  (Creator deposits bond & submits question/oracle spec)
     v
[ PENDING_LIQUIDITY ]
     |  (Requires >= MIN_INITIAL_LIQUIDITY in USDC)
     v
[ OPEN_TRADING ]
     |  (Users trade YES/NO shares via AMM / CLOB)
     v
[ TRADING_HALTED ]
     |  (Market Expiry Timestamp reached)
     v
[ RESOLUTION_PENDING ]
     |  (Oracle proposes outcome: YES / NO / INVALID)
     v
[ CHALLENGE_WINDOW ] ---> [ DISPUTED ] (Escalation to dispute council / UMA OO)
     | (No challenge)             |
     v                            v
[ RESOLVED ] <--------------------+ (Final consensus reached)
     |
     v
[ REDEMPTION ]
     (Winning token holders redeem $1.00 per share; creator redeems fees & bond)
```

### 4.1 State Definitions
1. **`CREATED`**: Market parameters registered on-chain via `PredictionMarketFactory`.
2. **`PENDING_LIQUIDITY`**: Waiting for creator or external LPs to meet the minimum collateral threshold.
3. **`OPEN_TRADING`**: Full order placement, liquidity addition, and token swapping enabled.
4. **`TRADING_HALTED`**: Triggered automatically when `block.timestamp >= expiryTimestamp`. No further trades or pool additions allowed.
5. **`RESOLUTION_PENDING`**: Designated oracle publishes proposed outcome.
6. **`CHALLENGE_WINDOW`**: Standard delay (e.g., 24-48 hours) where community can post a dispute bond if the proposed outcome contradicts criteria.
7. **`RESOLVED`**: Outcome is final. Winning shares are marked redeemable for underlying collateral.
8. **`CLOSED`**: All collateral claimed; market archived.

---

## 5. Smart Contract Architecture (Arbitrum One)

The smart contract subsystem is implemented in Solidity using Foundry, located under `contracts/src/`:

```text
contracts/src/prediction/
├── PredictionMarketFactory.sol    # Factory for deploying and tracking markets
├── PredictionMarket.sol           # Core market instance (collateral escrow & state)
├── ConditionalTokens.sol          # ERC-1155 outcome share token standard (CTF)
├── PredictionAMM.sol              # Constant-product or CPMM binary liquidity pool
├── PredictionFeeRouter.sol        # Splits trading fees between creator & ALGOXEN
└── oracles/
    ├── IPredictionOracle.sol      # Generic oracle resolution interface
    ├── UmaOptimisticAdapter.sol   # UMA Optimistic Oracle v3 adapter
    └── AlgoxenCuratedAdapter.sol  # Multi-sig / Pyth hybrid adapter for official markets
```

### 5.1 Key Interfaces & Method Signatures

#### `IPredictionMarketFactory.sol`
```solidity
interface IPredictionMarketFactory {
    struct MarketParams {
        string question;
        string resolutionSource;
        uint256 expiryTimestamp;
        uint256 resolutionTimestamp;
        address collateralToken; // Standard: Arbitrum Native USDC (0xaf88d065e77c8cC2239327C5EDb3A432268e5831)
        uint256 minLiquidity;
        address oracleAdapter;
        bool isOfficial;
    }

    event MarketCreated(
        bytes32 indexed marketId,
        address indexed marketAddress,
        address indexed creator,
        bool isOfficial
    );

    function createCommunityMarket(
        MarketParams calldata params,
        uint256 initialLiquidityAmount
    ) external returns (address marketAddress, bytes32 marketId);

    function createOfficialMarket(
        MarketParams calldata params
    ) external returns (address marketAddress, bytes32 marketId);
}
```

#### `IPredictionMarket.sol`
```solidity
interface IPredictionMarket {
    enum MarketState { Created, PendingLiquidity, Open, Halted, ResolutionPending, Disputed, Resolved }
    enum Outcome { Undecided, Yes, No, Invalid }

    function buyShares(Outcome outcome, uint256 minSharesOut, uint256 maxCollateralIn) external returns (uint256 sharesBought);
    function sellShares(Outcome outcome, uint256 sharesIn, uint256 minCollateralOut) external returns (uint256 collateralReturned);
    function addLiquidity(uint256 collateralAmount) external returns (uint256 lpTokensMinted);
    function removeLiquidity(uint256 lpTokenAmount) external returns (uint256 collateralReturned);
    function resolve(Outcome proposedOutcome) external;
    function dispute(bytes calldata evidence) external;
    function redeemWinnings(address account) external returns (uint256 payout);
    function claimCreatorFees() external returns (uint256 feesClaimed);
}
```

---

## 6. Tokenomics & AGX Value Accrual

Prediction markets are directly integrated into ALGOXEN's primary token economy (`AGX`):

1. **Protocol Fee Routing**:
   - 60% of all market trading fees in USDC are routed to `RewardClaims.sol`.
   - These fees increase the monthly discretionary reward pool distributed to locked AGX stakers based on snapshot-weighted stakes.
2. **AGX Staker Fee Discounts**:
   - Trading fees on prediction markets are tiered by AGX staking volume:
     - Tier 0 (0 AGX): 2.0% fee
     - Tier 1 (Bronze): 1.5% fee
     - Tier 2 (Silver): 1.0% fee
     - Tier 3 (Gold / Whale): 0.5% fee
3. **Creator Bond & Gas Subsidies**:
   - Community creators holding staked AGX enjoy discounted creation bond requirements and priority indexing on the ALGOXEN explorer.
4. **Governance & Dispute Voting**:
   - High-tier AGX stakers participate in the decentralized dispute escalation module for contested community market resolutions.

---

## 7. Backend Integration Requirements (`backend/`)

The FastAPI application manages off-chain market discovery, indexing, validation, rate limiting, and performance analytics.

### 7.1 Backend Architecture & File Responsibilities

| Path | Purpose |
| :--- | :--- |
| `backend/app/prediction_indexer.py` | Event listener syncing `MarketCreated`, `SharesTraded`, `LiquidityChanged`, `MarketResolved`. |
| `backend/app/prediction_state.py` | In-memory and persisted storage for market metadata, order depths, 24h volume, and odds. |
| `backend/app/schemas.py` | Pydantic validation models for market creation requests, queries, and resolution events. |
| `backend/app/main.py` | Public and admin REST endpoints. |

### 7.2 Core Endpoints

#### Public Endpoints
- `GET /prediction-markets`: Paginated list of markets with filters (`status`, `category`, `is_official`, `min_volume`).
- `GET /prediction-markets/{market_id}`: Detailed metadata, current YES/NO probability, pool reserves, resolution rules, and volume.
- `GET /prediction-markets/{market_id}/price-history`: Historical probability candlestick / line series for UI charts.
- `GET /prediction-markets/{market_id}/trades`: Real-time audit log of past swaps and redemptions.
- `GET /prediction-markets/user/{wallet_address}`: User positions, held shares, pending claims, and creator earnings.

#### Admin / Operator Endpoints
- `POST /admin/prediction-markets/official`: Deploy official ALGOXEN market with treasury seed allocation.
- `POST /admin/prediction-markets/{market_id}/flag`: Content moderation flag for offensive or illegal markets.
- `POST /admin/prediction-markets/{market_id}/resolve`: Operator fallback resolution hook for official markets.

---

## 8. Frontend Integration Requirements (`frontend/`)

The React + Vite frontend provides an intuitive, high-velocity trading terminal consistent with ALGOXEN's institutional design aesthetic:

### 8.1 Key Views & Components
1. **Market Directory (`/markets`)**:
   - Toggle: `Official ALGOXEN Markets` vs. `Community Permissionless Markets`.
   - Category tags: Crypto, Macroeconomics, Quant/DeFi, Tech, Pop Culture.
   - Search bar, sorting by 24h Volume, Liquidity, Newest, and Ending Soon.
2. **Trading Terminal (`/markets/:id`)**:
   - Probability banner (e.g., "72% YES | 28% NO").
   - Interactive price/odds chart over time (Chart.js or Lightweight Charts).
   - Order Execution Widget: Buy/Sell YES/NO with slippage protection, USDC balance check, and transaction approval state.
   - Resolution Criteria Drawer: Full transparent disclosure of exact sources, determination timestamps, and oracle addresses.
3. **Permissionless Creation Studio (`/markets/create`)**:
   - Guided multi-step wizard:
     1. Event Definition (Question, description, category, tags).
     2. Outcome Setup (Binary YES/NO or Multi-choice).
     3. Resolution & Timing (Expiry date, resolution criteria URL/API, oracle selection).
     4. Liquidity & Bond Funding (USDC approval, minimum pool deposit, anti-spam bond).
     5. On-chain deployment confirmation.
4. **Creator & Portfolio Dashboard (`/markets/portfolio`)**:
   - Active user positions with unrealized PnL.
   - One-click winning payout claims.
   - Creator tab showing accrued trading fee revenue and bond release status.

---

## 9. Risk Management, Moderation & Compliance

### 9.1 Ambiguity & Resolution Vulnerabilities
- Strict template validation prevents vague questions (e.g., "Will ETH reach high prices?"). Questions must have exact numeric conditions and verified data endpoints.
- In cases where real-world events become impossible to resolve or criteria fail, markets resolve to `INVALID`, returning 100% of collateral to token holders proportionally.

### 9.2 Regulatory & Legal Strategy
- Operating as an unhosted, permissionless software protocol running on public smart contracts.
- Geographic IP compliance screening (geofencing) applied at the frontend layer where required by local jurisdictional guidelines.
- Plain language disclaimers: prediction markets are event contracts for risk hedging and forecasting, not guaranteed yield vehicles (in accordance with ALGOXEN messaging rules in `SPEC.md`).

---

## 10. Implementation Phasing & Roadmap

```
+-----------------------------------------------------------------------------------+
| PHASE 1: CORE INFRASTRUCTURE & BENCHMARK MARKETS                                  |
| - Deploy CTF conditional tokens & CPMM AMM contracts on Arbitrum Sepolia/One      |
| - Launch Official ALGOXEN-seeded markets with Multi-sig/Pyth resolution           |
| - Deliver basic frontend trading interface and backend event indexer              |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| PHASE 2: PERMISSIONLESS FACTORY & CREATOR ECONOMICS                               |
| - Deploy PredictionMarketFactory with anti-spam bond & min liquidity gate         |
| - Roll out Creator Fee Split engine (40% creator / 60% ALGOXEN protocol)          |
| - Launch Frontend Creation Studio wizard and Creator Earnings Dashboard           |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| PHASE 3: DECENTRALIZED ORACLES & AGX REWARD INTEGRATION                           |
| - Integrate UMA Optimistic Oracle v3 for automated community dispute settlement   |
| - Connect FeeRouter directly to RewardClaims.sol for monthly AGX staker payout    |
| - Implement AGX staking fee discount tiers and dispute governance escalation      |
+-----------------------------------------------------------------------------------+
```
