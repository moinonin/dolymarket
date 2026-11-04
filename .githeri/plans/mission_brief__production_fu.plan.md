# Feature

Name: prediction-market-platform
Purpose: Production Prediction Market Platform with Off-Chain CLOB, CTF Settlement Simulation, and Real-Time WebSocket Streaming

Reference Specification: Format B (Structured Single-Feature YAML)

Expected Deliverables:
- Database schema and SQLAlchemy async models for complete domain state
- Authentication & multi-tenant user isolation layer (JWT / API key)
- Off-chain Central Limit Order Book (CLOB) engine with price-time priority and dynamic fee calculation
- Conditional Tokens Framework (CTF) settlement and dispute resolution engine
- FastAPI REST endpoints for markets, orders, positions, and oracle operations
- WebSocket server for real-time order book snapshot/delta streaming and execution fills
- Pytest test suite covering unit, integration, and invariant checks

Dependencies:
- `fastapi`
- `sqlalchemy`
- `pydantic`
- `pytest`
- `pytest-asyncio`
- `httpx`
- `bcrypt`
- `aiosqlite`

Assumptions:
- Environment provides Python 3.10+
- SQLite in-memory database used via `sqlite+aiosqlite:///:memory:` for async test/development lifecycle
- Authentication secret provided via environment variable `JWT_SECRET`

---

# Target Environment

OS: Linux / macOS / POSIX shell environment
Language: Python 3.10+
Framework: FastAPI
ORM: SQLAlchemy (Async IO with `aiosqlite`)
Test Framework: pytest / pytest-asyncio

---

# Global Success Criteria

1. **Schema Completeness**: All 9 primary domain entities (`User`, `CollateralAccount`, `Event`, `Market`, `OutcomeToken`, `Order`, `TradeFill`, `Position`, `OracleDispute`) are defined with proper indices, foreign keys, and status enumerations.
2. **CLOB Matching Integrity**: Off-chain matching engine strictly enforces tick integrity ($0.01 \le p \le 0.99$, $p \bmod \text{tick\_size} = 0$) and executes dynamic fee deduction using formula $Fee = C \times feeRate \times p \times (1 - p)$.
3. **Settlement Invariant**: Market resolution pays exactly 1.00 USDC per winning outcome token share and 0.00 USDC per losing token share. Total payout equals collateral locked.
4. **Multi-User Isolation**: Cross-user unauthorized order cancellations, position accesses, or collateral modifications return HTTP `403 Forbidden`.
5. **Real-Time Streaming**: WebSocket connections receive broadcast order book depth updates (L2) and trade execution ticks (L3) upon every matched trade.
6. **Automated Test Pass**: Entire test suite under `tests/` passes without errors or warnings via `pytest tests/`.

---

# Execution Stages

## Stage 1: Domain Data Models & Database Infrastructure Setup

### Objective
Define SQLAlchemy async models for all 9 core domain entities (`User`, `CollateralAccount`, `Event`, `Market`, `OutcomeToken`, `Order`, `TradeFill`, `Position`, `OracleDispute`) and establish database engine initialization.

### Inputs
- Specification blueprint for models
- Package dependencies: `sqlalchemy`, `aiosqlite`

### Preconditions
- Python virtual environment is active with required packages installed (`sqlalchemy`, `aiosqlite`, `pydantic`).

### Discovery Tasks
- Inspect current repository directory structure for pre-existing models or database initialization modules.
- Verify SQLAlchemy version compatibility for `declarative_base` and async session handling (`AsyncSession`, `create_async_engine`).

### Execution Tasks
1. Create source directory structure `app/db/` and `app/models/`.
2. Create `app/db/session.py` to expose the async engine and `get_async_session` dependency using `DATABASE_URL`.
3. Create `app/models/domain.py` containing SQLAlchemy model classes:
   - `User`: user metadata, email, password hash, API key.
   - `CollateralAccount`: balance, locked_balance, currency (USDC).
   - `Event`: slug, title, description, category, tags, status.
   - `Market`: event_id, title, condition_id, outcome_count, tick_size, fee_rate, status.
   - `OutcomeToken`: market_id, index, symbol, name.
   - `Order`: user_id, market_id, outcome_index, side (BUY/SELL), price, quantity, filled_quantity, status (OPEN, FILLED, CANCELLED).
   - `TradeFill`: maker_order_id, taker_order_id, price, quantity, fee_amount, timestamp.
   - `Position`: user_id, market_id, outcome_index, quantity.
   - `OracleDispute`: market_id, disputer_id, proposed_outcome, bond_amount, status.
4. Create `tests/test_models.py` to test asynchronous model creation and table instantiation.

### Suggested Commands
```bash
mkdir -p app/db app/models tests
python -c "import sqlalchemy; print(sqlalchemy.__version__)"
pytest tests/test_models.py
```

### Expected Outputs
- `app/db/session.py`
- `app/models/domain.py`
- `tests/test_models.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1-1  | `python -c "from app.models.domain import User, CollateralAccount, Event, Market, OutcomeToken, Order, TradeFill, Position, OracleDispute; print('Models Imported Successfully')"` | Models Imported Successfully |
| L1-2  | `pytest tests/test_models.py` | 100% PASS |

### Failure Procedure
If database model initialization fails:
1. Stop execution.
2. Inspect tracebacks for missing Foreign Keys or invalid Column types.
3. Verify `aiosqlite` backend compatibility with `SQLite` dialect.
4. Correct `app/models/domain.py` and re-run local verification commands.

### Completion Condition
All 9 models import cleanly and `pytest tests/test_models.py` executes with exit code 0.

---

## Stage 2: Authentication & Multi-Tenant Collateral Management

### Objective
Implement user registration, login, JWT token issuance/verification, collateral balance tracking, and strict multi-user access isolation.

### Inputs
- `app/models/domain.py`
- Security libraries: `bcrypt`, `PyJWT` (or `jose`), `fastapi` security utilities
- Environment variables: `JWT_SECRET`

### Preconditions
- Stage 1 completed successfully with passing model checks.

### Discovery Tasks
- Inspect requirements for password hashing (use `bcrypt`).
- Inspect required HTTP error codes for unauthorized actions (`401 Unauthorized`, `403 Forbidden`).

### Execution Tasks
1. Create `app/core/security.py` for password hashing, password verification, and JWT access token creation/decoding.
2. Create `app/api/deps.py` for FastAPI dependency injection (`get_current_user`).
3. Create `app/services/collateral.py` to manage user account balances: deposit, lock collateral, release collateral, deduct fees.
4. Create `app/api/v1/auth.py` exposing POST `/api/v1/auth/register` and POST `/api/v1/auth/login`.
5. Create `app/api/v1/collateral.py` exposing GET `/api/v1/collateral/balance` and POST `/api/v1/collateral/deposit`.
6. Implement strict ownership checks: ensure users cannot query or mutate balances belonging to another `user_id`.
7. Create `tests/test_auth_collateral.py` to verify authentication flow, collateral locking, and multi-user isolation enforcement.

### Suggested Commands
```bash
mkdir -p app/core app/api/v1 app/services
pytest tests/test_auth_collateral.py
```

### Expected Outputs
- `app/core/security.py`
- `app/api/deps.py`
- `app/services/collateral.py`
- `app/api/v1/auth.py`
- `app/api/v1/collateral.py`
- `tests/test_auth_collateral.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L2-1  | `pytest tests/test_auth_collateral.py -k "test_jwt_and_auth"` | PASS |
| L2-2  | `pytest tests/test_auth_collateral.py -k "test_multi_user_isolation"` | PASS (Assert HTTP 403 / Access Denied when cross-accessing accounts) |
| L2-3  | `pytest tests/test_auth_collateral.py -k "test_collateral_locking"` | PASS |

### Failure Procedure
If access isolation or JWT validation fails:
1. Stop execution.
2. Inspect JWT signature validation in `app/core/security.py`.
3. Check balance calculation logic to ensure locked balances do not exceed available funds.
4. Revise source code and rerun `pytest tests/test_auth_collateral.py`.

### Completion Condition
Authentication and collateral isolation unit/integration tests pass completely.

---

## Stage 3: Off-Chain CLOB Matching Engine & Dynamic Fee Engine

### Objective
Implement the in-memory/off-chain Central Limit Order Book (CLOB) matching engine with price-time priority, tick integrity validation, price bounds ($0.01 \le p \le 0.99$), and dynamic fee calculations ($Fee = C \times feeRate \times p \times (1 - p)$).

### Inputs
- Business Rule: Dynamic Fee Calculation $Fee = C \times feeRate \times p \times (1 - p)$
- Business Rule: Price Bounds & Tick Integrity ($0.01 \le price \le 0.99$ and $price \pmod{tick\_size} = 0$)
- Models: `Order`, `TradeFill`, `Position`

### Preconditions
- Stages 1 and 2 completed successfully.

### Discovery Tasks
- Inspect mathematical precision requirements for order prices and quantities (`Decimal` precision vs `float`).
- Inspect double-entry accounting requirements for maker and taker orders during a match.

### Execution Tasks
1. Create `app/engine/clob.py` defining `OrderBook` and `MatchingEngine` classes.
2. Implement validation methods for incoming limit orders: