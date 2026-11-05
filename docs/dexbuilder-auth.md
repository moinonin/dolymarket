# DexBuilder authentication

Credentialed access to the DexBuilder prediction API uses the upstream's
HMAC-SHA512 scheme. The secret is only used locally to sign requests — it is
never sent to the upstream and never returned by the API.

## Configuration

```bash
DEXBUILDER_API_BASE=https://api.dexbuilder.com
DEXBUILDER_API_KEY=<your API key>
DEXBUILDER_API_SECRET=<your API secret>
```

Both values are read from the environment or from a local `.env` file. The
proxy namespace `/api/v4/dexbuilder/*` answers HTTP 503
`DEXBUILDER_NOT_CONFIGURED` while `DEXBUILDER_API_KEY` is empty; the public
live routes keep working without any credential.

## Request headers

| Header | Value |
|---|---|
| `KEY` | the API key |
| `Timestamp` | unix timestamp in **seconds** (the upstream rejects a request more than 60 s away from its own clock) |
| `SIGN` | hexadecimal HMAC-SHA512 digest of the signed message |

## The signed message

```text
METHOD + "\n" +
PATH + "\n" +
QUERY + "\n" +
HexEncode(SHA512(raw body)) + "\n" +
TIMESTAMP
```

* `METHOD` — uppercase (`GET`, `POST`, `PUT`, `DELETE`).
* `PATH` — request path only, no scheme, host or port, e.g.
  `/api/v4/prediction/usertrades`.
* `QUERY` — the query string exactly as sent, same parameter order, not
  re-sorted. Use an empty string when there are no query parameters (the line
  is still present).
* `HexEncode(SHA512(raw body))` — SHA512 of the exact bytes sent. An empty body
  hashes to
  `cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e`.
* `TIMESTAMP` — the same value that is sent in the `Timestamp` header.

The signature is then:

```text
SIGN = HexEncode(HMAC_SHA512(api_secret, signed message))
```

### Worked example

```text
GET
/api/v1/dex_futures/usdt/orders
status=finished&limit=50
cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e
1541993715
```

!!! warning "Never log the secret"
    The API secret must never be sent to the upstream, written into frontend
    code or pasted into a ticket, chat or screenshot. If it leaks, disable the
    key and create a new one.

## Upstream error labels

| Label | Meaning |
|---|---|
| `MISSING_REQUIRED_HEADER` | one of `KEY`, `Timestamp`, `SIGN` was not sent |
| `REQUEST_EXPIRED` | the `Timestamp` is more than 60 s away from the server clock (seconds, not milliseconds) |
| `INVALID_KEY` | the API key does not exist, is disabled or was copied wrong — the upstream checks the key **before** the signature, so this label never means "wrong signature" |
| `INVALID_SIGNATURE` | the signed message or the secret is wrong |
| `IP_FORBIDDEN` | the calling IP is not on the key's allow list |
| `READ_ONLY` | a read-only key called a write endpoint |
| `FORBIDDEN` | the account or key has no permission for that operation |

Locally a rejected credential surfaces as HTTP 502
`DEXBUILDER_UPSTREAM_UNAUTHORIZED`, and the upstream label is returned in the
`X-Upstream-Error` response header.

## Credential diagnostic

```bash
curl "http://localhost:8000/api/v4/prediction/live/auth"
```

```json
{
  "configured": true,
  "key_present": true,
  "secret_present": true,
  "scheme": "HMAC-SHA512",
  "headers": ["KEY", "Timestamp", "SIGN"],
  "authenticated": false,
  "upstream": {
    "status": 401,
    "label": "INVALID_KEY",
    "message": "Invalid key provided"
  }
}
```

The diagnostic never returns the key or the secret. `authenticated: true` means
the upstream accepted the credential; `configured: false` means the
environment is missing the key or the secret. The Live page shows the same
state as an **Auth** badge next to the DexBuilder chip.

## WebSocket authentication

Private websocket channels (`pred.orders`, `pred.usertrades`,
`pred.positions`, `pred.settlements`) use the same key with a different signed
message:

```text
channel=<channel>&event=<event>&time=<unix milliseconds>
```

signed with HMAC-SHA512 and sent as:

```json
{
  "t": 1720000000123,
  "id": "private-1",
  "op": "subscribe",
  "ch": "pred.orders",
  "payload": { "all": true },
  "auth": { "method": "api_key", "key": "YOUR_API_KEY", "sign": "HEX_SIGNATURE" }
}
```

The upstream broker currently answers HTTP 503 for every channel, so private
streaming cannot be verified yet.
