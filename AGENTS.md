# Agent Guidelines & Repository Operational Rules (`AGENTS.md`)

This repository is governed by strict agent operational rules designed for autonomous coding agents (Antigravity, Cursor, Claude Code, Gemini CLI, Codex, Hermes, Pi, etc.).

---

## 🔒 1. Strict Privacy & Path Rule: No Absolute User Paths

> [!CRITICAL]
> **NEVER HARDCODE ABSOLUTE SYSTEM PATHS OR USER HOME DIRECTORIES**  
> Under no circumstances may an agent write, generate, or commit absolute local file system paths containing usernames or host directory structures (e.g., `/Users/<username>/...`, `file:///Users/<username>/...`, `/home/<username>/...`, or `C:\Users\<username>\...`).

### Path Formatting Rules
1. **Always Use Repository-Relative Paths**:
   - In all `.md` files, documentation, runbooks, benchmarks, code comments, and test scripts, refer to files using relative paths from the repository root:
     - ✅ `docs/benchmarks/SWE_GYM_EXECUTION_REPORT.md`
     - ✅ `scripts/test_swebench_live_fix.py`
     - ✅ `specgen-web/src/DocsPage.tsx`
     - ❌ `file:///Users/username/Desktop/portfolio/projects/python/ai/githeri/...`
     - ❌ `/Users/username/Desktop/portfolio/projects/python/ai/githeri/...`
2. **Markdown Hyperlinks**:
   - Use relative repository links: `[Label](path/to/file.py)` or `[Label](path/to/file.py#L10-L20)`.
   - Never prefix markdown links with `file:///` protocols containing local disk paths.
3. **Executable Scripts**:
   - Resolve repository roots dynamically:
     ```python
     from pathlib import Path
     REPO_ROOT = Path(__file__).resolve().parent.parent  # Or appropriate parent depth
     ```

### ⚠️ Strict Command & Filesystem Scoping: Zero Global Disk Scans
- **NEVER run global root filesystem searches** (`find /`, `grep -rn ... /`, `ls /`, etc.).
- Global root searches crawl OS volumes, snapshot backups, and external drives, hanging agent execution indefinitely.
- **Strictly scope all shell and search commands to the local workspace (`.`) or virtual environment (`.venv`)**:
  - ✅ `find . -name "*.py" -not -path "*/.*"`
  - ✅ `grep -rn "symbol" src/ tests/`
  - ✅ `which githeri` or `.venv/bin/pip list`
  - ❌ `find / -name "githeri"`
  - ❌ `grep -r "verify" /`

---

## 📐 2. Contract-First Development (The Githeri Protocol)

Before generating or modifying backend code, always ensure a verified specification exists to prevent route drift, broken database schemas, and multi-turn hallucination loops:

1. **Synthesize & Lock Spec**:
   - Run `githeri plan "<natural language request>"` to synthesize requirements, filter diagnostic noise, and generate:
     - A validated contract specification in `.githeri/specs/<feature>.spec.yaml`
     - A phased, step-by-step checklist in `.githeri/plans/<feature>.plan.md`
2. **No Assumptions & No Simplifications**:
   - Never assume, simplify, or water down requirements because a file or task seems "complex".
   - Never replace production cryptographic, authentication, database, or business logic with "clean" or "simplified" stubs.
   - Implement the complete production specifications as contracted. Simplification is considered a failure.
3. **Dynamic Business Logic & Formula Execution (Zero Hardcoded Stubs)**:
   - **Never return static hardcoded scalars or dummy responses** in core controllers (e.g. `readiness_score = 85`, `refined = f"Refined: {prompt}"`, or static fixed entity lists) where the specification contracts dynamic evaluation formulas, calculations, or business logic.
   - Implement the actual business logic, scoring formulas, entity extraction, and state transitions contracted under the spec's `business_rules` section.
   - Write tests that assert variable outputs for varied inputs (e.g., assert that an empty concept scores lower than an enriched concept).
4. **Phased Implementation Execution**:
   - **Phase 1: Schemas & Database Models**
   - **Phase 2: Route & Controller Implementation**
   - **Phase 3: Automated Verification Tests (Pytest / HTTP)**
5. **AST Grounding & Surgical Splicing**:
   - When modifying existing codebases, **do NOT regenerate entire files**.
   - Use AST targeting to isolate the target class or method, write only the replacement AST node, and surgically inject it to prevent import hallucinations and file drift.
6. **Cryptographic & Authentication Hygiene**:
   - **NEVER use unmaintained `passlib`**. In Python 3.11+, `passlib.context.CryptContext` has known incompatibilities with modern `bcrypt >= 4.0`, throwing `ValueError: password cannot be longer than 72 bytes`.
   - Always use native `bcrypt` (`bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()`) or standard library `hashlib` (`hashlib.sha256` with salt / `hmac.compare_digest`).

---

## 🎨 3. Full-Stack & Frontend Operational Rules (`frontend/`, `specgen-web/`)

When generating or modifying frontend code in full-stack projects or UI packages:

1. **Static Verification Only (NEVER Run Dev Servers)**:
   - **NEVER execute `npm run dev`**, `vite`, `npm start`, or `next dev`. Dev servers block the terminal process and hang agent execution indefinitely.
   - Always verify frontend changes statically:
     ```bash
     cd frontend && npm run build
     ```
   - Both TypeScript type-checking (`tsc -b`) and Vite production bundling must exit cleanly with code 0.

2. **Zero Hardcoded Localhost URLs**:
   - **NEVER hardcode `http://localhost:8000`** or `http://127.0.0.1:8000` inside frontend components.
   - Always import and use the scaffolded, type-safe API client:
     ```typescript
     import { apiClient } from './api/client'
     ```
   - For custom endpoints, resolve from environment with relative fallbacks:
     ```typescript
     const API_BASE = import.meta.env.VITE_API_URL || ''
     ```

3. **Live Contract Binding (No Mock Data Arrays)**:
   - **NEVER leave fake mock data arrays** (`const MOCK_ITEMS = [...]`) in production views.
   - Wire all UI views (lists, tables, modals, forms, and detail drawers) to real backend routes via `apiClient`.
   - Every data-fetching view MUST handle:
     - **Loading State**: Spinners or skeleton loaders while awaiting response.
     - **Empty State**: Clear placeholder message and creation CTA when list/table is empty.
     - **Error State**: User-facing banner or toast on network/HTTP errors.

4. **Component Surgery & Modern CSS Integrity**:
   - Maintain modern Tailwind CSS v4 styling: keep `@tailwindcss/vite` in `vite.config.ts` and `@import "tailwindcss";` in `src/index.css`.
   - **NEVER create obsolete `tailwind.config.js`** or conflicting PostCSS configs that break Vite v4 builds.
   - Use Lucide icons (`lucide-react`) for consistent UI iconography.
   - Do not regenerate entire component trees; isolate and update the target component.

5. **Domain-Specific UI Customization (Never Leave Generic "Item" Scaffolds)**:
   - Githeri scaffolds full-stack starter templates with generic entities (e.g., `Item`, `ItemList.tsx`, `ItemFormModal.tsx`, `ItemDetailDrawer.tsx`).
   - Adapt and rename components and models to reflect the real business domain (e.g., `ProjectList.tsx`, `StudioInceptionModal.tsx`, `ProjectDrawer.tsx`).
   - Ensure headings, CTAs, status badges, and forms use domain-accurate terms matching the product vision (e.g., "Founder Playground Studio", "Launch Project", "Readiness Gauge", not "Item Management").

---

## 🛡️ 4. Dual Pre-Completion Verification Gate

Before completing any task or ending your turn:
1. **Backend Verification**:
   - Run `githeri verify` (or `pytest`).
   - Do NOT run blocking background servers (`uvicorn`, `flask run`, `sleep`, or `curl` loops).
   - Do NOT watch streaming logs (`tail -f`).
   - If an ephemeral server process is ever started for quick health verification, you MUST kill its PID (`kill -9 $PID`) before the command or turn ends. Never leave background servers running.
   - `githeri verify` automatically performs static defect checks (Ruff F821), boot import checks, contract audits, and executes the test suite in-memory without background server daemons.
2. **Frontend Verification** (if `frontend/` or `specgen-web/` modified):
   - Run `npm run build` in the frontend directory.
   - Verify 0 TypeScript compilation errors and clean bundle output.
3. If verification reports missing endpoints, import failures, or test crashes:
   - Fix the code implementation to match the specification contract and pass all tests.
   - Do NOT modify or dilute the contract spec unless explicitly instructed by the user.
4. A task is only complete once ALL verification gates pass with exit code 0.

---

## ⚡ 5. Communication Style (Caveman Mode)

- When interacting in session, respect user global configuration: activate concise, direct, terse caveman mode (`/caveman full`).
- Eliminate conversational preamble, repetition, and corporate boilerplate. Keep outputs direct and actionable.
