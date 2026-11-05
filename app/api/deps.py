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


async def _user_from_api_key(
    request: Request, session: AsyncSession, api_key: str
) -> User:
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
