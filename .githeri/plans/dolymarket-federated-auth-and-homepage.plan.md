# Feature

Name: dolymarket-federated-auth-and-homepage
Purpose: Add OAuth, WebAuthn passkeys, and public marketing homepage
Reference Specification: Dolymarket Federated Auth and Homepage Specification (Format B YAML)
Expected Deliverables:
- SQLAlchemy models (`User`, `OAuthAccount`, `PasskeyCredential`, `PasskeyChallenge`, `AuthExchangeCode`) in `app/models/domain.py`
- OAuth 2.0 authorization, status, and one-time exchange routes in `app/api/v1/oauth.py`
- WebAuthn passkey registration, login, and credential management routes in `app/api/v1/passkey.py`
- Current user session profile route in `app/api/v1/auth.py`
Dependencies:
- fastapi
- sqlalchemy
- pydantic
- pytest
- httpx
- webauthn
- pyjwt
Assumptions:
- Python environment is pre-configured with required packages installed or installable via pip.
- Database connection strings are handled via environment configuration.

---

# Global Success Criteria

1. SQLAlchemy models for linked OAuth accounts, passkey credentials, ceremony challenges, and one-time exchange codes are correctly defined with foreign keys.
2. OAuth start, callback, provider status, and exchange endpoints return correct payloads, and exchange codes can be redeemed exactly once.
3. Passkey register and login endpoints issue challenges and tokens successfully, with stored sign counters incremented on every successful assertion.
4. GET `/api/v1/auth/me` returns the authenticated profile and rejects anonymous calls.
5. POST `/api/v1/auth/oauth/exchange` successfully exchanges a valid code for a JWT and rejects a replayed code.
6. POST `/api/v1/auth/passkey/login/verify` authenticates a valid passkey assertion and returns a JWT while rejecting invalid signatures or replayed challenges.

---

# Execution Stages

## Stage 1: Domain Models

### Objective
Create SQLAlchemy models for linked OAuth accounts, passkey credentials, ceremony challenges, and one-time exchange codes.

### Inputs
- Specification requirements for `User`, `OAuthAccount`, `PasskeyCredential`, `PasskeyChallenge`, and `AuthExchangeCode`.

### Preconditions
- Python project structure exists with database base configuration.

### Discovery Tasks
- Inspect existing project structure and directory layout (`app/models/`).
- Verify SQLAlchemy Base and session management modules.

### Execution Tasks
- Read existing domain model files if any exist.
- Inspect database base configuration and helper utilities (`_uuid`, `_now_utc`).
- Create or update `app/models/domain.py` with `User`, `OAuthAccount`, `PasskeyCredential`, `PasskeyChallenge`, and `AuthExchangeCode` models.
- Run tests to verify schema definition.

### Suggested Commands
```bash
python -m pytest tests/
```

### Expected Outputs
- `app/models/domain.py` containing the required database models.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L1    | python -c "from app.models.domain import OAuthAccount; print(OAuthAccount.__tablename__)" | oauth_accounts |

### Failure Procedure
If verification fails: stop immediately, diagnose configuration/syntax errors or missing helpers, revise code, and re-run verification.

### Completion Condition
L1 local verification check returns PASS.

---

## Stage 2: OAuth Endpoints

### Objective
Implement OAuth 2.0 authorization endpoints, provider status, and exchange routes.

### Inputs
- `app/models/domain.py`
- FastAPI routing patterns and Pydantic schemas.

### Preconditions
- Stage 1 completed successfully (models exist).

### Discovery Tasks
- Inspect existing API routing structure under `app/api/v1/`.
- Inspect security/JWT token generation utilities.

### Execution Tasks
- Read existing API routes and dependencies.
- Create `app/api/v1/oauth.py` implementing provider status, start, callback, and exchange routes.
- Ensure exchange codes are single-use.
- Mount or register the OAuth router in the main FastAPI application.
- Run test suite.

### Suggested Commands
```bash
python -m pytest tests/
```

### Expected Outputs
- `app/api/v1/oauth.py` containing OAuth endpoints.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L2    | python -c "from app.api.v1.oauth import router; print(router.prefix)" | (Empty or configured prefix matching specification) |

### Failure Procedure
If verification fails: stop immediately, diagnose routing or business rule issues, revise implementation, and re-run verification.

### Completion Condition
L2 local verification check returns PASS.

---

## Stage 3: Passkey Endpoints

### Objective
Implement WebAuthn passkey registration and login endpoints.

### Inputs
- `app/models/domain.py`
- `webauthn` library specifications and FastAPI router setup.

### Preconditions
- Stage 1 completed successfully (models exist).

### Discovery Tasks
- Inspect existing API routing structure under `app/api/v1/`.
- Inspect WebAuthn library integration requirements (RP ID, Origin).

### Execution Tasks
- Read existing API code.
- Create `app/api/v1/passkey.py` with endpoints for registration options/verify, login options/verify, credential listing, and deletion.
- Ensure sign counter incrementing logic is implemented on assertions.
- Register passkey router in the main FastAPI application.
- Run test suite.

### Suggested Commands
```bash
python -m pytest tests/
```

### Expected Outputs
- `app/api/v1/passkey.py` containing WebAuthn endpoints.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L3    | python -c "from app.api.v1.passkey import router; print(router)" | Router instance present |

### Failure Procedure
If verification fails: stop immediately, diagnose WebAuthn validation or payload handling issues, revise code, and re-run verification.

### Completion Condition
L3 local verification check returns PASS.

---

## Stage 4: Session Profile Endpoint

### Objective
Implement the session profile endpoint used by the frontend shell.

### Inputs
- Authentication dependency (`get_current_user`).
- `User` model.

### Preconditions
- Stages 1-3 completed successfully.

### Discovery Tasks
- Inspect authentication dependencies and existing auth route files.

### Execution Tasks
- Read existing authentication logic in `app/api/v1/auth.py`.
- Add or update the `/api/v1/auth/me` endpoint to return user ID, email, and creation timestamp.
- Run test suite.

### Suggested Commands
```bash
python -m pytest tests/
```

### Expected Outputs
- Updated `app/api/v1/auth.py` containing the `me` endpoint.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L4    | python -c "from app.api.v1.auth import me; print(me.__name__)" | me |

### Failure Procedure
If verification fails: stop immediately, diagnose dependency injection or token decoding issues, revise implementation, and re-run verification.

### Completion Condition
L4 local verification check returns PASS.

---

## Stage 5: OAuth Exchange Verification

### Objective
Verify that the OAuth exchange endpoint returns a JWT access token and rejects replayed codes.

### Inputs
- Running FastAPI application instance.
- Test client or HTTP client (`httpx`).

### Preconditions
- Stages 1 through 4 completed successfully.

### Discovery Tasks
- Inspect test configuration and test client setup (`tests/`).

### Execution Tasks
- Ensure test database and server fixtures are ready.
- Execute HTTP integration test for the OAuth exchange endpoint.

### Suggested Commands
```bash
curl -s -X POST "http://localhost:8000/api/v1/auth/oauth/exchange" -H "Content-Type: application/json" -d '{"code": "test-exchange-code"}'
```

### Expected Outputs
- Test execution results showing successful exchange and rejection of replayed codes.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L5    | curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:8000/api/v1/auth/oauth/exchange" -H "Content-Type: application/json" -d '{"code": "invalid"}' | 400 or 401/422 (depending on error handling for invalid/missing codes) |

### Failure Procedure
If verification fails: stop immediately, diagnose token exchange state handling or database constraints, revise implementation, and re-run verification.

### Completion Condition
L5 verification criteria pass successfully.

---

## Stage 6: Passkey Login Verification

### Objective
Verify that the passkey login verify endpoint issues a JWT access token and rejects invalid signatures or replayed challenges.

### Inputs
- Running FastAPI application instance.
- Passkey verification test fixtures.

### Preconditions
- Stages 1 through 5 completed successfully.

### Discovery Tasks
- Inspect passkey test cases in `tests/`.

### Execution Tasks
- Execute HTTP integration test for passkey login verification.

### Suggested Commands
```bash
pytest tests/test_passkey.py
```

### Expected Outputs
- Passing test assertions for passkey login verification.

### Local Verification
| Check | Command | Expected |
|-------|---------|----------|
| L6    | pytest tests/test_passkey.py -k "login" | PASSED |

### Failure Procedure
If verification fails: stop immediately, diagnose WebAuthn challenge verification logic, signature validation, or sign counter checks, revise implementation, and re-run verification.

### Completion Condition
L6 verification criteria pass successfully.

---

# Global Verification

Once every stage passes, perform complete project validation:

1. **Build Verification**: Ensure all modules compile and import without errors.
   ```bash
   python -c "import app.models.domain, app.api.v1.oauth, app.api.v1.passkey, app.api.v1.auth; print('All modules imported successfully')"
   ```
2. **Full Test Suite**: Run the complete test suite.
   ```bash
   pytest tests/
   ```
3. **Integration & Endpoint Verification**: Confirm all authentication routes (`/api/v1/auth/me`, `/api/v1/auth/oauth/*`, `/api/v1/auth/passkey/*`) respond correctly according to specification business rules.