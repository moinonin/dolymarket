"""FastAPI dependency injection for authenticated users.

Supports two credential styles:

* ``Authorization: Bearer <jwt>`` for the browser client
* ``X-API-KEY`` + ``X-TIMESTAMP`` + ``X-SIGNATURE`` for algorithmic traders,
  where the signature is HMAC-SHA256 over
  ``TIMESTAMP + METHOD + PATH + BODY``
"""
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.session import get_async_session
from app.models.domain import User

bearer_scheme = HTTPBearer(auto_error=False)

_AUTH_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)

_HMAC_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid API key, timestamp or HMAC signature",
)


_HMAC_REPLAY_CACHE: dict[str, float] = {}


async def _user_from_api_key(
    request: Request, session: AsyncSession, api_key: str
) -> User:
    import time

    timestamp = request.headers.get("X-TIMESTAMP", "")
    signature = request.headers.get("X-SIGNATURE", "")
    if not timestamp or not signature or not security.timestamp_fresh(timestamp):
        raise _HMAC_ERROR

    body = await request.body()
    if not security.verify_hmac_signature(
        api_key,
        timestamp,
        request.method,
        request.url.path,
        body,
        signature,
    ):
        raise _HMAC_ERROR

    digest = security.api_key_digest(api_key)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        now_m = time.monotonic()
        replay_key = f"{digest}:{timestamp}:{signature}"
        exp = _HMAC_REPLAY_CACHE.get(replay_key)
        if exp is not None and exp > now_m:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Replayed HMAC mutation rejected",
            )
        if len(_HMAC_REPLAY_CACHE) >= 10000:
            expired = [k for k, v in _HMAC_REPLAY_CACHE.items() if v <= now_m]
            for k in expired:
                _HMAC_REPLAY_CACHE.pop(k, None)
        _HMAC_REPLAY_CACHE[replay_key] = now_m + security.HMAC_TOLERANCE_SECONDS

    user = (
        await session.execute(select(User).where(User.api_key == digest))
    ).scalar_one_or_none()
    if user is None:
        raise _HMAC_ERROR
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    api_key = request.headers.get("X-API-KEY")
    if api_key:
        return await _user_from_api_key(request, session, api_key)

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _AUTH_ERROR
    user = (
        await session.execute(select(User).where(User.id == payload.get("sub")))
    ).scalar_one_or_none()
    if user is None:
        raise _AUTH_ERROR
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin-only dependency: the server is the authority on admin routes.

    Shared by every privileged surface (admin console, oracle resolution) so
    authorization is declared on the route, not left to an inline check the
    handler can forget to call.
    """
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN_REQUIRED"
        )
    return user
