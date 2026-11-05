# COMMAND_RUNWAY: dexbuilder-credentialed-auth

# Feature
**Name:** dexbuilder-credentialed-auth
**Purpose:** Sign upstream DexBuilder requests the way the official spec documents, surface credential rejection explicitly, and make the credential state observable.
**Reference Specification:** `.githeri/specs/dexbuilder-credentialed-auth.spec.yaml`
**Expected Deliverables:**
- `app/services/dexbuilder.py` — spec-accurate HMAC-SHA512 signing, credential error type, credential diagnostic.
- `app/api/v4/dexbuilder/proxy.py` — upstream credential failures map to `DEXBUILDER_UPSTREAM_UNAUTHORIZED`.
- `app/api/v4/prediction/live.py` — `GET /api/v4/prediction/live/auth` credential diagnostic.
- `frontend/src/api/client.ts`, `frontend/src/pages/LiveMarketsPage.tsx` — auth badge on the live page.
- `tests/test_dexbuilder_auth.py` — hermetic signing / rejection / diagnostic tests.

**Dependencies:**
- `fastapi`
- `httpx`
- `pydantic`

**Assumptions:**
- The upstream checks the API key before the signature, so `INVALID_KEY` means "key not registered upstream".
- Public upstream reads need no credentials and keep working unsigned.

---

# Global Success Criteria
- Requests are signed exactly as documented: `KEY`, `Timestamp` (seconds), `SIGN = HexEncode(HMAC_SHA512(secret, METHOD\nPATH\nQUERY\nHexEncode(SHA512(body))\nTIMESTAMP))`.
- The signed query string is byte-identical to the sent query string.
- An upstream 401/403 surfaces as `DEXBUILDER_UPSTREAM_UNAUTHORIZED` with the upstream label, never as a generic bad-response error.
- The credential diagnostic never returns the key or the secret.
- `pytest`, `ruff`, `githeri verify` and `npm run build` all pass.

---

# Phase 1 — Services
1. Replace the speculative SHA-256 signer with the documented scheme: `canonical_signature_message()` (five newline-separated lines) and `sign_payload()` (hex HMAC-SHA512).
2. Encode the query string once with `urlencode` in the same order it is sent and sign that exact string; assemble the URL so the sent query cannot drift from the signed one.
3. Add `DexBuilderAuthError` carrying the upstream label and raise it on HTTP 401/403; keep `MISSING_REQUIRED_HEADER` / `REQUEST_EXPIRED` labels intact for diagnostics.
4. Add `DexBuilderClient.check_credentials()` — probes `/api/v4/prediction/usertrades` and reports configured / scheme / upstream label without leaking secrets.

# Phase 2 — Routes
1. Map `DexBuilderAuthError` in `app/api/v4/dexbuilder/proxy.py` to HTTP 502 `DEXBUILDER_UPSTREAM_UNAUTHORIZED` with the `X-Upstream-Error` header.
2. Add `GET /api/v4/prediction/live/auth` returning the credential diagnostic (configured, scheme, authenticated, upstream status/label/message).
3. Show the credential state as a badge on the live markets page.

# Phase 3 — Verification
1. `tests/test_dexbuilder_auth.py` with an httpx `MockTransport`: canonical message against the documented example, signed-query fidelity, credential rejection, proxy mapping, diagnostic payload.
2. `pytest -q`, `ruff check app tests --select F821,F811,E9`, `githeri verify`, `npm run build`, `mkdocs build --strict`.
3. Update `docs/dexbuilder-todo.md` and `docs/live-data.md` with the signing scheme and how to read the diagnostic.
