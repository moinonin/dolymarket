# Frontend Implementation Plan: `polymarket-dexbuilder-prediction-platform`

**Target Entity**: `User`  
**Framework**: `React + TypeScript + Tailwind CSS`  
**Reference Backend Contract**: `.githeri/specs/polymarket-dexbuilder-prediction-platform.spec.yaml`  

---

## Visual Design Mandates (`frontend-design` Protocol)
> [!IMPORTANT]
> **ZERO AI CLICHÉS**: Strictly avoid default generated AI styles:
> 1. **NO WARM CREAM BACKGROUNDS** (near `#F4F1EA`) with high-contrast serif display text.
> 2. **NO UNIFORM SAAS CARD KITS**: Avoid chopping every section into identical rounded cards with soft grey shadows (`rgba(0,0,0,0.1)`).
> 3. **NO TRACKED-OUT ALL-CAPS EYEBROWS** or non-sequential `01/02/03` badges.
> 4. **PURPOSEFUL TYPOGRAPHY**: Use an intentional type scale with crisp contrast.
> 5. **DOMAIN-SPECIFIC PALETTE**: Ground colors in the application subject matter (e.g. emerald for active status, slate for cancelled, amber for expired).
> 6. **ACTION-TRIGGERED MOTION**: Restrict motion to user action feedback (drawers opening, confirmations, toasts).

---

## Phased Execution Runway

### Stage 0: Backend Server Gateway & Static Serving (app/main.py or src/main.py)
- Add CORS middleware (`CORSMiddleware(allow_origins=['*'])`) so Vite dev server (`http://localhost:5173`) can communicate with `/api`.
- Mount compiled static assets (`frontend/dist`) on root `/` (`StaticFiles(directory='frontend/dist', html=True)`) so `http://localhost:8000` immediately serves the built React app.

### Stage 1: API Client & Data Models (`src/api/client.ts`)
- Implement type-safe API client matching all spec endpoints:
- Ensure error responses (404, 422) are captured cleanly with descriptive UI toasts.
- Propagate user authentication headers and handle `HTTP 401/403` ownership/permission errors with clear UI feedback.

### Stage 2: Main Overview & Collection View (`src/components/UserList.tsx`)
- Mount table / card grid listing all `User` records (`GET /...`).
- Include distinctive loading skeletons and clear, actionable empty state with a 'Create' action trigger.
- Add status filter controls for: all statuses.

### Stage 3: Creation & Mutation Modals (`src/components/UserFormModal.tsx`)
- Interactive form for `POST /...` with client-side validation reflecting backend rules:
  - **Price Boundary**: `0.01 <= price <= 0.99`
  - **Parabolic Fee Model**: `fee = C * feeRate * p * (1 - p)`
  - **Atomic Settlement**: `winning token = 1.00 USDC, losing token = 0.00 USDC`
- Direct inline feedback on validation errors without jarring layout shifts.

### Stage 4: Inspection & State Transitions (`src/components/UserDetailDrawer.tsx`)
- Slide-over drawer to inspect single `User` (`GET /.../{id}`).
- Actions for status transitions (`PUT /.../{{id}}`) and deletion confirmation modal (`DELETE /.../{{id}}`).

### Stage 5: Verification & Production Build Gate
Run automated checks before declaring completion:
```bash
npm run build
```
- Verify zero TypeScript compiler errors (`tsc --noEmit`).
- Verify production bundle builds cleanly with exit code 0.
