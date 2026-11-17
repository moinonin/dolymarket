# Feature

Name: automate-market-resolution-end-to-end
Purpose: Automate local and community market resolution end-to-end with backend worker and frontend UI

Reference Specification
- Business Rules:
  1. Oracle Resolution Parameters: Markets support `oracle_feed`, `oracle_threshold`, and `oracle_comparator` fields.
  2. Idempotent Background Worker: Lifespan worker periodically closes ACTIVE markets, proposes resolution for CLOSED markets via oracle, and finalizes uncontested IN_RESOLUTION markets.

Expected Deliverables
- SQLAlchemy Market model extension incorporating oracle parameters (`src/models/market_extension.py`).
- Asynchronous background resolution worker implementation (`src/workers/resolution_worker.py`).
- Market resolution API endpoint supporting test resolution triggers.

Dependencies
- Packages: `fastapi`, `sqlalchemy`, `pydantic`, `pytest`, `httpx`

Assumptions
- Database connection relies on `DATABASE_URL` environment variable (`sqlite:///./test.db`).
- FastAPI application runs locally on `http://localhost:8000`.

---

# Global Success Criteria

- Complete test suite passes successfully via `pytest tests/`.
- Market database models properly reflect oracle resolution fields.
- Background worker loops execute resolution lifecycle phases idempotently.
- API endpoints respond correctly to market resolution requests.

---

# Execution Stages

## Stage 1: Market Model Extension

### Objective
Create and verify the SQLAlchemy Market model extensions supporting oracle resolution parameters (`oracle_feed`, `oracle_threshold`, `oracle_comparator`).

### Inputs
- Existing database models in the project
- Specification blueprint for `src/models/market_extension.py`

### Preconditions
- Python environment initialized with SQLAlchemy and FastAPI dependencies installed.

### Discovery Tasks
- Inspect existing project structure and database base models under `src/models/`.
- Verify database configuration and ORM setup.

### Execution Tasks
- Read existing model definitions to understand base class structures and conventions.
- Inspect current database session configurations.
- Create or update the market model extension file at `src/models/market_extension.py`.
- Integrate oracle fields (`oracle_feed`, `oracle_threshold`, `oracle_comparator`) into the model architecture.
- Run database migrations or schema updates if required.

### Suggested Commands
```bash
python -c "import sqlalchemy; print(sqlalchemy.__version__)"
pytest tests/
```

### Expected Outputs
- File: `src/models/market_extension.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1    | test -f src/models/market_extension.py && grep -q "oracle_threshold" src/models/market_extension.py && echo "PASS" || echo "FAIL" | PASS |

### Failure Procedure
- Stop immediately upon verification failure.
- Diagnose root cause (e.g., incorrect syntax, missing SQLAlchemy imports, path mismatch).
- Produce a corrective execution plan and repeat Stage 1.

### Completion Condition
- Local Verification check L1 returns `PASS`.

---

## Stage 2: Background Resolution Worker Implementation

### Objective
Create and verify the asynchronous background resolution worker loop (`src/workers/resolution_worker.py`) that periodically handles market lifecycle states (closing active markets, proposing resolutions via oracle, and finalizing uncontested resolutions).

### Inputs
- Specification blueprint for `src/workers/resolution_worker.py`
- Application configuration and logging modules

### Preconditions
- Stage 1 completed successfully (Market model extensions available).

### Discovery Tasks
- Inspect existing worker structures or task management utilities in the codebase.
- Inspect FastAPI lifespan event handlers or background task configurations.

### Execution Tasks
- Read existing application startup/shutdown hooks.
- Create the worker file at `src/workers/resolution_worker.py`.
- Implement the asynchronous worker loop (`run_resolution_worker`) with error handling and sleep intervals.
- Wire the worker into the FastAPI application lifespan/startup sequence if applicable.

### Suggested Commands
```bash
python -c "import asyncio; print('Asyncio ready')"
pytest tests/
```

### Expected Outputs
- File: `src/workers/resolution_worker.py`

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L2    | test -f src/workers/resolution_worker.py && grep -q "run_resolution_worker" src/workers/resolution_worker.py && echo "PASS" || echo "FAIL" | PASS |

### Failure Procedure
- Stop immediately upon verification failure.
- Diagnose root cause (e.g., syntax errors, missing asyncio imports, incorrect file path).
- Produce a corrective execution plan and repeat Stage 2.

### Completion Condition
- Local Verification check L2 returns `PASS`.

---

## Stage 3: Market Resolution API Endpoint

### Objective
Implement and verify the market resolution API endpoint (`/api/markets/resolve-test`) ensuring it processes requests successfully and returns expected status codes.

### Inputs
- FastAPI routing and controller modules
- Database session dependencies

### Preconditions
- Stage 1 and Stage 2 completed successfully.
- FastAPI server running locally on `http://localhost:8000`.

### Discovery Tasks
- Inspect existing API routers, route prefixes, and dependency injection patterns under `src/api/` or equivalent.
- Inspect test client configurations (`httpx` / `pytest`).

### Execution Tasks
- Read existing route definitions.
- Implement or update the market resolution endpoint supporting POST requests to `/api/markets/resolve-test`.
- Write or update corresponding unit/integration tests utilizing `httpx` and `pytest`.

### Suggested Commands
```bash
# Start FastAPI application for testing (example command)
uvicorn src.main:app --reload --port 8000 &
# Run HTTP verification check
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/markets/resolve-test -H "Content-Type: application/json" -d '{"market_id": 1}'
```

### Expected Outputs
- API endpoint handler for market resolution tests
- Updated API router registrations
- Integration tests

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L3    | curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/markets/resolve-test -H "Content-Type: application/json" -d '{"market_id": 1}' | 201 |

### Failure Procedure
- Stop immediately upon verification failure.
- Diagnose root cause (e.g., server not running, route not registered, invalid request body schema, database constraint violation).
- Produce a corrective execution plan and repeat Stage 3.

### Completion Condition
- Local Verification check L3 returns HTTP status `201`.

---

# Global Verification

Once every stage passes, perform complete project validation:

1. **Build Verification**: Ensure all modules compile and load without import errors.
   ```bash
   python -c "import src.models.market_extension; import src.workers.resolution_worker; print('Imports OK')"
   ```

2. **Full Test Suite**: Execute the complete test runner.
   ```bash
   pytest tests/
   ```

3. **Environment and Database Verification**: Confirm schema integrity under `DATABASE_URL=sqlite:///./test.db`.

Only after every global verification succeeds may the COMMAND_RUNWAY declare the feature complete.