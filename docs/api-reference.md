# API reference

Base URL: `http://localhost:8000` (relative in production).

## Auth
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`
- `GET /api/v1/auth/me` (reports `id`, `email`, `created_at` and `is_admin`)
- `GET /api/v1/auth/oauth/{provider}/start|callback`, `POST /api/v1/auth/oauth/exchange`
- `POST /api/v1/auth/passkey/register/options|verify`, `POST /api/v1/auth/passkey/login/options|verify`
- `GET/DELETE /api/v1/auth/passkey/credentials`

## Markets
- `GET /api/v4/prediction/events`, `/events/{id}`, `/events/slug/{slug}`
- `GET /api/v4/prediction/markets`, `/markets/{id}`, `/markets/slug/{slug}`
- `GET /api/v4/prediction/tags`
- `GET /api/v4/prediction/tokens/{id}/order_book`, `/price`, `/price_history`, `/ticker`, `/candlesticks`, `/market`
- `GET /api/v4/prediction/tokens/prices`

## Trading
- `POST /api/v4/prediction/orders`, `GET /orders`, `DELETE /orders`, `DELETE /orders/{id}`
- `GET /api/v4/prediction/markets/{id}/trades`

## Portfolio
- `GET /api/v4/prediction/positions`, `/positions/settled`
- `POST /positions/merge`, `/split`, `/positions/{id}/redeem`

## Resolution
- `POST /api/v4/prediction/resolution/propose|finalize|dispute`

## Pro Desks
- `GET/POST /api/v1/desks`, `GET /desks/mine`, `GET/PUT /desks/{id}`, submit/suspend/archive
- `GET /desks/{id}/track-record`, `/followers`, `/copy-jobs`
- `POST/PUT/DELETE /desks/{id}/follow`, `GET /copy-jobs`

## DexBuilder proxy
- `GET /api/v4/dexbuilder/*` (markets, events, tags, tokens, positions, usertrades, orders, time)

## Live DexBuilder
- `GET /api/v4/prediction/live/status`, `/live/auth`, `/live/markets`, `/live/markets/{id}`,
  `/live/events`, `/live/tags`, `/live/time`, `/live/tokens/{id}/order_book`,
  `/live/tokens/{id}/price_history`, `/live/tokens/{id}/candlesticks`, `/live/markets/{id}/trades`

## Admin (admin accounts only)
- `POST /api/v4/prediction/admin/events`, `POST /admin/markets`, `POST /admin/markets/{id}/close`
- `GET /api/v4/prediction/admin/desks` (review queue, `status` defaults to `PENDING_REVIEW`)
- `POST /api/v4/prediction/admin/desks/{id}/approve|reject|suspend`
- `GET /api/v4/prediction/admin/copy-jobs` (copy history across accounts)

Every admin route answers HTTP 403 `ADMIN_REQUIRED` for a regular account.

## WebSockets
- `GET /api/v4/prediction/ws/public`, `/ws/private`