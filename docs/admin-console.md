# Operations console

The **Operations console** is an admin-only area of the app (route `#/admin`)
for running the market and copy-trading operations. It is only visible in the
navigation for accounts with `is_admin = true`; every route under
`/api/v4/prediction/admin/*` answers HTTP 403 `ADMIN_REQUIRED` for a regular
account.

## Tabs

### Markets
- **Create event** — slug, title, category (and optional description / tags /
  end date). Slug must be unique.
- **Create market** — pick an event slug, write the question, and list the
  outcomes (comma separated, 2–10). The market is created `ACTIVE` with one
  outcome token per outcome.
- **Open markets** — lists every active market with its id and outcomes. Each row
  has a **Close market** button that moves the market `ACTIVE → CLOSED` and halts
  trading (orders can no longer be placed; resolution can then be proposed).

### Desk review
A queue of Pro Desks waiting for review. Filter by lifecycle state
(`PENDING_REVIEW`, `ACTIVE`, `SUSPENDED`, `REJECTED`, `ARCHIVED`, `DRAFT`).

Each card shows the desk name, owner email, follower count, status and the
review note (if any). Actions:

- **Approve** — desk becomes `ACTIVE` and appears in the public leaderboard.
- **Reject** — requires a written reason; the owner sees it on their desk.
- **Suspend** — temporarily takes a desk out of the leaderboard.

### Copy activity
A cross-account audit of every copy job: desk name, follower email, status,
copy ratio, requested/filled shares, error code and timestamp. Filter by
status (`PENDING`, `FILLED`, `REJECTED`, `SKIPPED`, `LIMIT_BREACHED`) and
refresh on demand. A summary row shows job / filled / rejected / limit-hit
counts and the requested vs filled share totals.

## Trader-facing copy activity

Non-admin traders see their own copy jobs under **Activity** (`#/activity`):
`GET /api/v1/copy-jobs`, scoped to the signed-in account, with the desk id,
status, ratio, requested/filled shares and any error code.

## Admin bootstrap

Accounts are promoted to admin in the database:

```sql
UPDATE users SET is_admin = TRUE WHERE email = 'you@example.com';
```

In tests, use the `make_admin(email)` helper from `tests/conftest.py`. The
`is_admin` flag is also reported by `GET /api/v1/auth/me` so the client can
show the console only to admins — but the server stays the authority on every
admin route.

## API

See [API reference](api-reference.md) § Admin. All admin routes answer
`403 ADMIN_REQUIRED` for a regular account.