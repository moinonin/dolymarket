# COMMAND_RUNWAY: dexbuilder-integration-parity

# Feature
**Name:** dexbuilder-integration-parity  
**Purpose:** Implement DexBuilder API parity, server-side proxy client, and missing prediction surfaces locally.  
**Reference Specification:** Format B Structured YAML  
**Expected Deliverables:** 
- DexBuilder HMAC-signed service client.
- Extended prediction API routes (Tags, Bulk Prices, User Trades).
- DexBuilder Proxy Router with configuration-based availability.
- Integration test suite for parity verification.

**Dependencies:**
- `fastapi`
- `httpx`
- `pydantic`
- `sqlalchemy`

**Assumptions:**
- Environment variables `DEXBUILDER_API_KEY` and `DEXBUILDER_API_SECRET` are managed via Pydantic `BaseSettings`.
- The project follows a standard FastAPI structure (`app/services`, `app/api/v4`).

---

# Global Success Criteria
- All money, price, and share values use `Decimal` with 4-point precision (18,4).
- Requests to DexBuilder are authenticated via HMAC-SHA256 signatures.
- Private routes enforce 401/403 status codes based on authentication state.
- Proxy routes return 503 if `DEXBUILDER_API_KEY` is not configured.
- Full test suite passes: `pytest tests/test_dexbuilder_parity.py` and `pytest tests/test_bulk_prices.py`.

---

# Execution Stages

## Stage 1: DexBuilder Service Client Implementation

### Objective
Create a server-side client capable of signing requests with HMAC-SHA256 and communicating with the DexBuilder API.

### Inputs
- `context.language`: Python
- `local_goals[L1].blueprint`

### Preconditions
- Python environment with `httpx` and `pydantic` installed.

### Discovery Tasks
- Inspect `app/services/` for existing client patterns.
- Verify if a global configuration/settings object already exists to integrate `DexBuilderConfig`.

### Execution Tasks
1. Create `app/services/dexbuilder.py`.
2. Define `DexBuilderConfig` using Pydantic `BaseSettings`.
3. Implement `DexBuilderClient` class.
4. Implement `_sign` method using `hmac` and `hashlib.sha256` as per blueprint.
5. Implement `get_markets` method using `httpx.AsyncClient`.

### Suggested Commands
- `ls app/services/`
- `cat app/core/config.py` (to check for existing settings)

### Expected Outputs
- `app/services/dexbuilder.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1    | `grep "class DexBuilderClient" app/services/dexbuilder.py` | Match found |
| L1    | `grep "hmac.new" app/services/dexbuilder.py` | Match found |

---

## Stage 2: Extended Prediction Routes

### Objective
Implement missing local prediction surfaces: Tags, Bulk Prices, and User Trades.

### Inputs
- `local_goals[L2].blueprint`
- `app/models/domain.py` (for `Market`, `TradeFill` references)

### Preconditions
- `app/api/v4/prediction/` directory exists.

### Discovery Tasks
- Inspect `app/models/domain.py` to ensure `Market` and `TradeFill` schemas align with the blueprint.
- Check `app/main.py` to see how routers are currently included.

### Execution Tasks
1. Create `app/api/v4/prediction/extended.py`.
2. Define `GET /tags` to return a list of strings.
3. Define `GET /tokens/prices` accepting a list of IDs; ensure return values use `Decimal("1.0000")`.
4. Define `GET /usertrades` with authentication dependency.
5. Register the new router in the main application entry point.

### Suggested Commands
- `mkdir -p app/api/v4/prediction`
- `pytest tests/test_bulk_prices.py` (Initial run to see failures)

### Expected Outputs
- `app/api/v4/prediction/extended.py`
- Updated router registration in `app/main.py` or equivalent.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L2    | `grep "def get_bulk_prices" app/api/v4/prediction/extended.py` | Match found |
| L4    | `curl -s -o /dev/null -w '%{http_code}' "http://localhost:8000/api/v4/prediction/tokens/prices?ids=1&ids=2"` | 200 |

---

## Stage 3: DexBuilder Proxy Router

### Objective
Implement a proxy router that forwards requests to the DexBuilder service, enforcing 503 errors if unconfigured.

### Inputs
- `local_goals[L3].blueprint`
- `app/services/dexbuilder.py`

### Preconditions
- Stage 1 (Client) is complete and verified.

### Discovery Tasks
- Verify the existence of `DEXBUILDER_API_KEY` in the environment.

### Execution Tasks
1. Create `app/api/v4/dexbuilder/proxy.py`.
2. Implement `get_db_client` dependency that checks for `api_key`.
3. Implement `GET /markets` proxy route using the `DexBuilderClient`.
4. Register the proxy router in the main application.

### Suggested Commands
- `export DEXBUILDER_API_KEY=""` (to test 503)
- `export DEXBUILDER_API_KEY="test_key"` (to test active)

### Expected Outputs
- `app/api/v4/dexbuilder/proxy.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L3    | `grep "async def proxy_markets" app/api/v4/dexbuilder/proxy.py` | Match found |
| L5    | `unset DEXBUILDER_API_KEY && curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v4/dexbuilder/markets` | 503 |

---

# Global Verification

### Build & Quality
- **Linting:** Run `flake8` or `black --check` on modified files.
- **Type Check:** Run `mypy app/services/dexbuilder.py`.

### Automated Tests
- **Parity Test:** `pytest tests/test_dexbuilder_parity.py`
- **Bulk Prices Test:** `pytest tests/test_bulk_prices.py`

### Manual Validation
- Verify that `GET /api/v4/prediction/tokens/prices` returns values with exactly 4 decimal places in the JSON response (e.g., `1.0000`).
- Verify that the `X-DB-SIGN` header is being generated correctly by the client (can be done via debug logs or a mock server).

---

# Failure Procedure
1. **Stop:** Do not proceed to the next stage.
2. **Diagnose:** Check if the failure is due to missing environment variables (`DEXBUILDER_API_SECRET`) or incorrect `Decimal` casting.
3. **Correct:** Update the implementation or the test fixture.
4. **Retry:** Re-run the Local Verification for the current stage.

# Execution Rules
1. Never skip stages.
2. Ensure `Decimal(18,4)` is used for all financial outputs.
3. If `DEXBUILDER_API_KEY` is missing, the proxy **must** return 503.
4. Preserve existing FastAPI dependency injection patterns.