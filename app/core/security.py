"""Password hashing (native bcrypt) and JWT issuance/verification (PyJWT)."""
import hashlib
import hmac
import os
import secrets
import uuid

import bcrypt
import jwt

# Fail fast rather than silently minting forgable tokens: a missing or
# publicly-known secret lets anyone forge a bearer JWT for any account.
# Set ALLOW_INSECURE_SECRETS=1 only for hermetic local/test runs.
_INSECURE_SECRETS_ALLOWED = os.environ.get("ALLOW_INSECURE_SECRETS", "").strip() == "1"
_KNOWN_WEAK_SECRETS = frozenset(
    {
        "",
        "test-secret-key-1234567890abcdef",
        "dev-secret-change-in-production",
        "secret",
        "changeme",
    }
)
_SECRET = os.environ.get("JWT_SECRET", "").strip()
if not _INSECURE_SECRETS_ALLOWED:
    if not _SECRET:
        raise RuntimeError(
            "JWT_SECRET is not set. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))" '
            "(set ALLOW_INSECURE_SECRETS=1 only for local test runs)."
        )
    if _SECRET in _KNOWN_WEAK_SECRETS:
        raise RuntimeError(
            "JWT_SECRET is a publicly known default; set a unique random secret."
        )
JWT_SECRET = _SECRET or "test-secret-key-1234567890abcdef"
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256").strip() or "HS256"
TOKEN_TTL_SECONDS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")) * 60


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return hmac.compare_digest(
            bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode(),
            hashed,
        ) or bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def verify_password_strict(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def unusable_password_hash() -> str:
    """Hash of a random secret for accounts that have no password.

    Federated (OAuth/passkey-only) accounts store this value so the
    ``hashed_password`` column stays non-nullable while no password can ever
    match it.
    """
    return hash_password(secrets.token_urlsafe(48))


_REVOKED_JTIS: dict[str, float] = {}
_WS_TICKETS: dict[str, tuple[str, float]] = {}


def revoke_jti(jti: str | None, exp: float | None = None) -> None:
    import time

    if not jti:
        return
    now = time.time()
    if len(_REVOKED_JTIS) >= 10000:
        for k in [k for k, v in _REVOKED_JTIS.items() if v <= now]:
            _REVOKED_JTIS.pop(k, None)
    _REVOKED_JTIS[jti] = exp if exp and exp > now else now + TOKEN_TTL_SECONDS


def is_jti_revoked(jti: str | None) -> bool:
    import time

    if not jti:
        return False
    exp = _REVOKED_JTIS.get(jti)
    if exp is None:
        return False
    if exp <= time.time():
        _REVOKED_JTIS.pop(jti, None)
        return False
    return True


def create_access_token(user_id: str, email: str) -> str:
    import time

    payload = {
        "sub": user_id,
        "email": email,
        "typ": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, email: str, ttl_seconds: int = 7 * 86400) -> str:
    import time

    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "typ": "refresh",
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("typ") == "refresh":
        raise jwt.InvalidTokenError("Refresh token cannot be used as access token")
    if is_jti_revoked(payload.get("jti")):
        raise jwt.InvalidTokenError("Token has been revoked")
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("typ") != "refresh":
        raise jwt.InvalidTokenError("Not a refresh token")
    if is_jti_revoked(payload.get("jti")):
        raise jwt.InvalidTokenError("Refresh token has been revoked")
    return payload


def create_ws_ticket(user_id: str, ttl_seconds: int = 30) -> str:
    import time

    now = time.monotonic()
    if len(_WS_TICKETS) >= 10000:
        for k in [k for k, (_, exp) in _WS_TICKETS.items() if exp <= now]:
            _WS_TICKETS.pop(k, None)
    ticket = secrets.token_urlsafe(24)
    _WS_TICKETS[ticket] = (user_id, now + ttl_seconds)
    return ticket


def consume_ws_ticket(ticket: str | None) -> str | None:
    import time

    if not ticket:
        return None
    entry = _WS_TICKETS.pop(ticket, None)
    if entry is None:
        return None
    user_id, exp = entry
    if exp <= time.monotonic():
        return None
    return user_id


STATE_TTL_SECONDS = 600


def create_signed_state(payload: dict, ttl_seconds: int = STATE_TTL_SECONDS) -> str:
    """Sign a short-lived state blob (used by the OAuth handshake).

    The state travels through the browser, so it must be tamper-proof: it
    carries the provider, the PKCE verifier and the post-login redirect
    target, and it expires after ``ttl_seconds``.
    """
    import time

    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + ttl_seconds, "jti": str(uuid.uuid4())}
    return jwt.encode(body, JWT_SECRET, algorithm=JWT_ALGORITHM)


def read_signed_state(token: str) -> dict:
    """Verify and decode a signed state blob. Raises on tamper/expiry."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_api_key(secret: str | None = None) -> tuple[str, str]:
    """Returns (api_key, verification_hash). api_key format: ``<id>.<secret>``."""
    key_id = str(uuid.uuid4())[:8]
    key_secret = secret or secrets.token_hex(20)
    api_key = f"{key_id}.{key_secret}"
    return api_key, api_key_digest(api_key)


def api_key_digest(api_key: str) -> str:
    """SHA-256 HMAC of a presented API key under the server secret.

    Only this digest is stored, so a database leak does not expose usable
    trading credentials.
    """
    return hmac.new(
        JWT_SECRET.encode(), api_key.encode(), hashlib.sha256
    ).hexdigest()


def split_api_key(api_key: str) -> str:
    """Return the secret portion of ``<key_id>.<secret>``."""
    _, _, secret = api_key.partition(".")
    return secret


def verify_api_key(api_key: str, digest: str) -> bool:
    return hmac.compare_digest(api_key_digest(api_key), digest)


HMAC_TOLERANCE_SECONDS = 300


def compute_hmac_signature(
    secret: str,
    timestamp: str,
    method: str,
    path: str,
    body: bytes | str,
) -> str:
    """HMAC-SHA256 over ``TIMESTAMP + METHOD + PATH + BODY``."""
    if isinstance(body, bytes):
        body_bytes = body
    else:
        body_bytes = body.encode()
    message = timestamp.encode() + method.upper().encode() + path.encode() + body_bytes
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def timestamp_fresh(timestamp: str, tolerance: int = HMAC_TOLERANCE_SECONDS) -> bool:
    import time

    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    return abs(int(time.time()) - ts) <= tolerance


def verify_hmac_signature(
    api_key: str,
    timestamp: str,
    method: str,
    path: str,
    body: bytes | str,
    signature: str,
) -> bool:
    secret = split_api_key(api_key)
    if not secret or not signature:
        return False
    expected = compute_hmac_signature(secret, timestamp, method, path, body)
    return hmac.compare_digest(expected, signature.lower())
