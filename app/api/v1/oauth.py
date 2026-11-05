"""OAuth 2.0 endpoints: start, callback and one-time token exchange."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.session import get_async_session
from app.services import oauth as oauth_service
from app.services.oauth import OAuthError, OAuthProvider

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["auth"])

FRONTEND_CALLBACK_ENV = "OAUTH_FRONTEND_CALLBACK"
DEFAULT_FRONTEND_CALLBACK = "/"


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=8, max_length=256)


def _callback_redirect_uri(request: Request, provider: OAuthProvider) -> str:
    base = os.environ.get("OAUTH_REDIRECT_BASE", "").strip()
    if base:
        return f"{base.rstrip('/')}/api/v1/auth/oauth/{provider.name}/callback"
    root = str(request.base_url).rstrip("/")
    return f"{root}/api/v1/auth/oauth/{provider.name}/callback"


def _frontend_callback_url(code: str) -> str:
    base = os.environ.get(FRONTEND_CALLBACK_ENV, "").strip() or DEFAULT_FRONTEND_CALLBACK
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}oauth_code={code}"


@router.get("/providers")
async def list_providers():
    """Which federated providers this deployment supports."""
    return {"providers": oauth_service.provider_status()}


@router.get("/{provider}/start")
async def oauth_start(
    provider: str,
    request: Request,
    redirect: bool = Query(default=False),
):
    """Build the provider authorize URL and a signed state token."""
    try:
        config = oauth_service.get_provider(provider)
    except OAuthError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc

    redirect_uri = _callback_redirect_uri(request, config)
    code_verifier, code_challenge = oauth_service.pkce_pair()
    state = security.create_signed_state(
        {
            "provider": config.name,
            "code_verifier": code_verifier,
            "redirect": bool(redirect),
        }
    )
    try:
        auth_url = oauth_service.build_authorize_url(
            config,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )
    except OAuthError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc

    return {
        "provider": config.name,
        "label": config.label,
        "configured": config.configured(),
        "auth_url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri,
    }


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
):
    """Complete the handshake and mint a one-time exchange code."""
    try:
        config = oauth_service.get_provider(provider)
    except OAuthError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc

    if error:
        raise HTTPException(status_code=400, detail=f"{config.label}: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        state_data = security.read_signed_state(state)
    except Exception as exc:  # any decode failure means a bad state
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    if state_data.get("provider") != config.name:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    redirect_uri = _callback_redirect_uri(request, config)
    try:
        tokens = await oauth_service.exchange_code(
            config,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=state_data.get("code_verifier"),
        )
        profile = await oauth_service.fetch_profile(config, tokens)
        user = await oauth_service.upsert_oauth_user(session, config, profile)
        exchange_code, expires_in = await oauth_service.create_exchange_code(
            session, user.id, provider=config.name
        )
    except OAuthError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc

    if state_data.get("redirect"):
        return RedirectResponse(url=_frontend_callback_url(exchange_code))
    return JSONResponse(
        {
            "exchange_code": exchange_code,
            "expires_in": expires_in,
            "provider": config.name,
        }
    )


@router.post("/exchange")
async def oauth_exchange(
    body: ExchangeRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Redeem a one-time exchange code for a JWT access token."""
    try:
        user = await oauth_service.consume_exchange_code(session, body.code)
    except OAuthError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc
    token = security.create_access_token(user.id, user.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": str(user.created_at),
        },
    }
