# COMMAND_RUNWAY: operations-console

# Feature
**Name:** operations-console
**Purpose:** Give admins a real console — create events and markets, close markets, review Pro Desks, inspect copy-job history — and make sure only admins can use the admin API.
**Reference Specification:** `.githeri/specs/operations-console.spec.yaml`
**Expected Deliverables:**
- `app/api/v4/admin.py` — admin enforcement on every route, desk review queue, copy-job history.
- `app/api/v1/auth.py` — `is_admin` in the profile payload.
- `frontend/src/pages/AdminPage.tsx` — console with markets, desk review and copy activity panels.
- `frontend/src/pages/CopyActivityPage.tsx` — the signed-in trader's own copy-job history.
- `frontend/src/api/client.ts`, `frontend/src/auth/AuthProvider.tsx`, `frontend/src/App.tsx` — client methods, admin flag, routes and nav.
- `tests/test_admin_console.py` — hermetic authorization and workflow tests.

**Dependencies:**
- `fastapi`
- `httpx`
- `pydantic`

**Assumptions:**
- `User.is_admin` is the only role flag; the server stays the authority.
- Copy jobs already exist in the database; the console only lists them.

---

# Global Success Criteria
- Every `/api/v4/prediction/admin/*` route answers HTTP 403 `ADMIN_REQUIRED` for a non-admin.
- `GET /api/v1/auth/me` reports `is_admin`.
- The console shows loading, empty and error states for every panel and renders no mock rows.
- `pytest`, `ruff`, `githeri verify` and `npm run build` all pass.

---

# Phase 1 — Backend
1. Apply the admin check to event creation, market creation and market closing.
2. Add `GET /api/v4/prediction/admin/desks` (review queue, default `PENDING_REVIEW`) and `GET /api/v4/prediction/admin/copy-jobs` (history across accounts with desk and follower labels).
3. Add `is_admin` to the auth profile payload and a shared `make_admin` test helper.

# Phase 2 — Frontend
1. Add the client methods for the admin queue, the desk review actions and the copy-job listings.
2. Carry `is_admin` through the auth provider and expose an admin-only nav entry and `#/admin` route.
3. Build `AdminPage.tsx` (create event, create market, market list with close, desk review queue, copy activity) and `CopyActivityPage.tsx` for the trader's own copy jobs.

# Phase 3 — Verification
1. `tests/test_admin_console.py`: non-admin rejection on every admin route, admin workflow, copy-job history, `is_admin` exposure.
2. Update the existing tests that created markets as non-admin accounts.
3. `pytest -q`, `ruff check app tests --select F821,F811,E9`, `githeri verify`, `npm run build`, `mkdocs build --strict`.
