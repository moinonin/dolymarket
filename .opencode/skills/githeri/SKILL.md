---
name: githeri
license: Apache-2.0
description: >
  Contract Engine for AI Coding Agents. Turns natural language feature requests into
  deterministic, validated YAML specifications and phased implementation checklists.
  Prevents agent hallucinations, route drift, and broken database schemas. Use whenever
  planning a new backend feature, designing API endpoints, or auditing implementation
  completeness before merging.
---

# Githeri: Contract Engine for AI Coding Agents

Githeri provides deterministic specifications and contract verification for AI coding agents.

## Why Use Githeri Before Coding?
When coding agents jump straight to writing backend code from fuzzy user instructions, they:
1. Hallucinate non-standard route names (`/api/user-login` vs `/v1/auth/login`).
2. Forget required validation error handling (400, 401, 422).
3. Miss database transaction boundaries and atomic state requirements.
4. Drift away from the original acceptance criteria.

Githeri stops this failure mode by inserting a **deterministic contract gate**:
```
User Request ──► Githeri Spec Engine ──► Validated YAML Spec ──► Code Implementation ──► Contract Verification
```

---

## Agent Workflow

### 1. Planning a New Feature
Whenever the user asks to implement or design a new feature or endpoint, first generate the contract:
```bash
githeri plan "Add user registration and JWT authentication endpoints"
```
Or to generate just the specification:
```bash
githeri spec "Add user registration and JWT authentication endpoints"
```
Or for machine-readable JSON output:
```bash
githeri spec --json "Add user registration and JWT authentication endpoints"
```

### 2. Inspecting the Contract
Inspect the generated spec at `.githeri/specs/<feature>.spec.yaml`:
- **`business_rules`**: Invariant rules that code MUST enforce.
- **`local_goals`**: Ordered blueprints for schemas, routes, and service logic.
- **`verification`**: Automated HTTP assertions and tests to prove the code works.

Follow the checklist in `.githeri/plans/<feature>.plan.md` step by step.

### 3. Verifying Implementation & Drift
Once code is written, run contract verification:
```bash
githeri verify
```
- **Exit 0**: All spec endpoints are matched and implemented in code.
- **Exit 1**: Missing endpoints or breaking schema drift detected. Fix the code before finishing the turn.

### 4. Native Model Context Protocol (MCP) Workflow (Sprint 15–18)
If connected via MCP (server `githeri-mcp`), call native tools directly without shell subprocesses:
1. `githeri_synthesize_contract`: Feature prompt in -> spec written to `.githeri/specs/<slug>.spec.yaml` + validated JSON returned.
2. `githeri_generate_plan`: Spec slug in -> `.githeri/plans/<slug>.plan.md` created with typed stages.
3. `githeri_patch_router`: Auto-mounts router in FastAPI entrypoint (`app.include_router`).
4. `githeri_verify_drift`: Returns structured verification report (`passed: bool`, `missing_endpoints: []`).
5. `githeri_verify_executability`: Runs static pytest collection + syntax checks (`pytest --collect-only`, `py_compile`).
6. `githeri_baseline_from_code`: Scans brownfield repo and emits draft baseline spec (`.githeri/specs/baseline.spec.yaml`).
7. `githeri_audit_report`: Generates full brownfield audit and contract coverage report.
8. `githeri_approve_spec`: Approves a reviewed draft spec (`status: approved`).

### 5. Running in CI/CD
For automated pull request audits:
```bash
githeri check-pr
```
Outputs GitHub Markdown summary highlighting contract coverage and blocking PR merge if endpoints are missing.
