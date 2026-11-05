# Dolymarket

Full-stack prediction market platform: FastAPI + SQLAlchemy CLOB backend, React/TypeScript frontend, conditional-token settlement, real-time WebSocket streaming, and a public marketing homepage with federated sign-in.

## Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, native `bcrypt`, PyJWT, `webauthn` (passkeys).
- **Matching**: in-memory price-time-priority order books with batched write-behind fills and monotonic stream sequences.
- **Frontend**: Vite + React + TypeScript + Tailwind CSS v4 + TradingView Lightweight Charts + `@simplewebauthn/browser`.
- **Testing**: hermetic pytest suite (`sqlite+aiosqlite:///:memory:`), no background servers required.

## Layout

```
app/
  api/            # auth, collateral, public discovery, orders, positions, resolution, WS
  api/v1/         # auth, collateral, oauth (Google/Microsoft/Apple), passkey (WebAuthn)
  core/           # security, HMAC, sequencer, rate limiter
  db/             # async session + demo seed
  engine/         # in-memory book, matching engine, fill queue
  services/       # collateral, CTF settlement, OAuth provider integration
  ws/             # connection manager, broadcaster, stream sequence
frontend/src/
  api/            # typed REST client, reconnecting socket, optimistic order store
  auth/           # session provider, federated sign-in controls
  components/     # trade ticket, depth ladder, charts, modals
  pages/          # home, markets, event detail, portfolio, resolution
tests/            # CLOB, auth, collateral, REST, OAuth, passkey, WebSocket verification
```

## Run

```bash
# backend (from repository root)
pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend (separate terminal)
cd frontend && npm install && npm run build
```

The backend serves `frontend/dist` at `/` after `cd frontend && npm run build`.

## Verification

```bash
pytest -q
cd frontend && npm run build
```

## Homepage & accounts

Anonymous visitors land on the marketing homepage (`/`): hero, live market
preview read from the public API, feature breakdown and sign-in calls to
action. Signed-in traders keep the terminal experience (markets, portfolio,
resolution).

Sign-in works with:

| Method | Endpoint(s) |
|---|---|
| Email + password | `POST /api/v1/auth/register`, `POST /api/v1/auth/login` |
| Session profile | `GET /api/v1/auth/me` |
| Google / Microsoft / Apple | `GET /api/v1/auth/oauth/{provider}/start` → `GET /api/v1/auth/oauth/{provider}/callback` → `POST /api/v1/auth/oauth/exchange` |
| Passkey (WebAuthn) | `POST /api/v1/auth/passkey/register/options`, `POST /api/v1/auth/passkey/register/verify`, `POST /api/v1/auth/passkey/login/options`, `POST /api/v1/auth/passkey/login/verify` |

The OAuth callback never returns a JWT through the URL. It mints a
single-use exchange code (5 minute TTL) that the frontend redeems exactly
once at `POST /api/v1/auth/oauth/exchange`. Provider credentials and the
WebAuthn relying-party settings come from the environment — see
[.env.example](.env.example). Unconfigured providers are reported by
`GET /api/v1/auth/oauth/providers` and their buttons are disabled.

Registered passkeys can be listed and revoked from the Portfolio → Security
tab (`GET`/`DELETE /api/v1/auth/passkey/credentials`).

## Algorithmic trading

1. `POST /api/v1/auth/api-key` with a bearer token to issue (or rotate) an API key.
2. Sign every request with:

```
X-SIGNATURE = hex(HMAC-SHA256(secret, X-TIMESTAMP + METHOD + PATH + BODY))
```

Send `X-API-KEY`, `X-TIMESTAMP`, and `X-SIGNATURE`. Timestamps must be within 300 seconds.

Order submissions accept `X-Idempotency-Key`; retries replay the original response instead of matching twice. Rate limits: 50 order requests/second per credential, 100 public reads/minute per IP.

## Streaming

Public WebSocket: `/api/v4/prediction/ws/public`.

Messages carry `stream_sequence`. Clients detect gaps, request `{"action":"resync","token_id":"..."}`, and the reconnect wrapper re-fetches `GET /api/v4/prediction/tokens/{id}/order_book` before applying new deltas.

## Documentation

- [docs/improve.md](docs/improve.md) — production architecture improvement notes.
- [AGENTS.md](AGENTS.md) — repository operational rules for coding agents.
