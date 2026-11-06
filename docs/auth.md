# Authentication

- **Email + password** (min 8 chars). Passwords hashed with native bcrypt.
- **Passkeys** (WebAuthn) — Face ID, Touch ID, security keys. Local dev works on
  `http://localhost:8000` (localhost is a secure context). If you serve the
  frontend from a different origin (for example the Vite dev server on
  `localhost:5173`), set `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN` and
  `WEBAUTHN_ORIGINS` to match, otherwise registration fails with HTTP 400 on
  the verify step. Production requires HTTPS and the production domain in those
  variables. See [Collateral](portfolio/collateral.md) for the wallet side.
- **Federated** — Google, Microsoft, Apple (OAuth 2.0 authorization code with
  PKCE and a one-time exchange code; no JWT in the URL).
- **API keys** — HMAC-SHA256 signed requests for algorithmic traders.

Session profile: `GET /api/v1/auth/me`. Providers: `GET /api/v1/auth/oauth/providers`.