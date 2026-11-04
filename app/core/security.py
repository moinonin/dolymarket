"""Password hashing (native bcrypt) and JWT issuance/verification (PyJWT)."""
import hashlib
import hmac
import os
import secrets
import uuid

import bcrypt
import jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-key-1234567890abcdef")
JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 60 * 60 * 24


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


def create_access_token(user_id: str, email: str) -> str:
    import time

    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_api_key(secret: str | None = None) -> tuple[str, str]:
    """Returns (api_key, verification_hash). api_key format: ``<id>.<secret>``."""
    key_id = str(uuid.uuid4())[:8]
    key_secret = secret or secrets.token_hex(20)
    api_key = f"{key_id}.{key_secret}"
    digest = hmac.new(JWT_SECRET.encode(), api_key.encode(), hashlib.sha256).hexdigest()
    return api_key, digest


def verify_api_key(api_key: str, digest: str) -> bool:
    computed = hmac.new(
        JWT_SECRET.encode(), api_key.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, digest)
