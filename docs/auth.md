# Authentication

- **Email + password** (min 8 chars). Passwords hashed with native bcrypt.
- **Passkeys** (WebAuthn) — Face ID, Touch ID, security keys.
- **Federated** — Google, Microsoft, Apple (OAuth 2.0 authorization code with
  PKCE and a one-time exchange code; no JWT in the URL).
- **API keys** — HMAC-SHA256 signed requests for algorithmic traders.

Session profile: `GET /api/v1/auth/me`. Providers: `GET /api/v1/auth/oauth/providers`.