"""OAuth 2.0 / OpenID Connect provider integration.

Implements the authorization-code flow for Google, Microsoft (Azure AD / OIDC)
and Apple. Everything provider specific lives here so the HTTP layer only
deals with the contract:

``GET  /api/v1/auth/oauth/{provider}/start``     -> provider authorize URL
``GET  /api/v1/auth/oauth/{provider}/callback``  -> one-time exchange code
``POST /api/v1/auth/oauth/exchange``             -> JWT access token

Provider credentials are read from the environment. A provider without
credentials is reported as ``configured=False`` instead of failing at
runtime, so the UI can hide the button rather than break the sign-in page.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.domain import AuthExchangeCode, OAuthAccount, User
from app.services import collateral

HTTP_TIMEOUT_SECONDS = 15.0
EXCHANGE_CODE_TTL_SECONDS = 300


@dataclass(frozen=True)
class OAuthProvider:
    """Static description of a supported identity provider."""

    name: str
    label: str
    client_id_env: str
    client_secret_env: str
    authorize_url: str
    token_url: str
    userinfo_url: str | None
    jwks_url: str | None
    scope: str
    supports_pkce: bool = True
    tenant_env: str | None = None

    def client_id(self) -> str | None:
        value = os.environ.get(self.client_id_env, "").strip()
        return value or None

    def client_secret(self) -> str | None:
        value = os.environ.get(self.client_secret_env, "").strip()
        return value or None

    def tenant(self) -> str:
        if self.tenant_env:
            return os.environ.get(self.tenant_env, "common").strip() or "common"
        return "common"

    def configured(self) -> bool:
        return bool(self.client_id())

    def authorize_endpoint(self) -> str:
        if self.tenant_env:
            return self.authorize_url.format(tenant=self.tenant())
        return self.authorize_url

    def token_endpoint(self) -> str:
        if self.tenant_env:
            return self.token_url.format(tenant=self.tenant())
        return self.token_url

    def jwks_endpoint(self) -> str | None:
        if not self.jwks_url:
            return None
        if self.tenant_env:
            return self.jwks_url.format(tenant=self.tenant())
        return self.jwks_url


GOOGLE = OAuthProvider(
    name="google",
    label="Google",
    client_id_env="GOOGLE_CLIENT_ID",
    client_secret_env="GOOGLE_CLIENT_SECRET",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
    jwks_url="https://www.googleapis.com/oauth2/v3/certs",
    scope="openid email profile",
)

MICROSOFT = OAuthProvider(
    name="microsoft",
    label="Microsoft",
    client_id_env="MICROSOFT_CLIENT_ID",
    client_secret_env="MICROSOFT_CLIENT_SECRET",
    authorize_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    userinfo_url="https://graph.microsoft.com/oidc/userinfo",
    jwks_url="https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
    scope="openid email profile",
    tenant_env="MICROSOFT_TENANT",
)

APPLE = OAuthProvider(
    name="apple",
    label="Apple",
    client_id_env="APPLE_CLIENT_ID",
    client_secret_env="APPLE_CLIENT_SECRET",
    authorize_url="https://appleid.apple.com/auth/authorize",
    token_url="https://appleid.apple.com/auth/token",
    userinfo_url=None,
    jwks_url="https://appleid.apple.com/auth/keys",
    scope="name email",
    supports_pkce=False,
)

PROVIDERS: dict[str, OAuthProvider] = {
    p.name: p for p in (GOOGLE, MICROSOFT, APPLE)
}


class OAuthError(Exception):
    """Raised when a provider handshake fails."""

    def __init__(self, detail: str, http_status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.http_status = http_status


def get_provider(name: str) -> OAuthProvider:
    provider = PROVIDERS.get((name or "").strip().lower())
    if provider is None:
        raise OAuthError(f"Unknown OAuth provider: {name}", http_status=404)
    return provider


def provider_status() -> list[dict]:
    """Public description of the supported providers and their readiness."""
    return [
        {
            "name": p.name,
            "label": p.label,
            "configured": p.configured(),
            "scopes": p.scope,
        }
        for p in PROVIDERS.values()
    ]


# --------------------------------------------------------------------------- #
# Handshake helpers
# --------------------------------------------------------------------------- #
def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def build_authorize_url(
    provider: OAuthProvider,
    redirect_uri: str,
    state: str,
    code_challenge: str | None = None,
) -> str:
    """Compose the provider's authorize URL."""
    client_id = provider.client_id()
    if not client_id:
        raise OAuthError(
            f"{provider.label} sign-in is not configured on this server",
            http_status=503,
        )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
    }
    if code_challenge and provider.supports_pkce:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    query = "&".join(f"{k}={_quote(v)}" for k, v in params.items())
    return f"{provider.authorize_endpoint()}?{query}"


def _quote(value: str) -> str:
    return quote(str(value), safe="")


async def exchange_code(
    provider: OAuthProvider,
    code: str,
    redirect_uri: str,
    code_verifier: str | None = None,
) -> dict:
    """Exchange an authorization code for provider tokens."""
    client_id = provider.client_id()
    client_secret = provider.client_secret()
    if not client_id:
        raise OAuthError(
            f"{provider.label} sign-in is not configured on this server",
            http_status=503,
        )

    payload: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if code_verifier and provider.supports_pkce:
        payload["code_verifier"] = code_verifier
    if provider.name == "apple":
        payload["client_secret"] = _apple_client_secret(provider)
    else:
        if not client_secret:
            raise OAuthError(
                f"{provider.label} sign-in is not configured on this server",
                http_status=503,
            )
        payload["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                provider.token_endpoint(), data=payload, headers={"Accept": "application/json"}
            )
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        raise OAuthError(f"Could not reach {provider.label}: {exc}", 502) from exc

    if response.status_code >= 400:
        raise OAuthError(
            f"{provider.label} rejected the authorization code "
            f"({response.status_code})",
            http_status=400,
        )
    data = response.json()
    if not isinstance(data, dict) or not data.get("access_token"):
        raise OAuthError(f"{provider.label} returned no access token", 502)
    return data


def _apple_client_secret(provider: OAuthProvider) -> str:
    """Apple accepts either a static secret or a signed ES256 client JWT."""
    private_key = os.environ.get("APPLE_PRIVATE_KEY", "").strip()
    team_id = os.environ.get("APPLE_TEAM_ID", "").strip()
    key_id = os.environ.get("APPLE_KEY_ID", "").strip()
    client_id = provider.client_id()
    if private_key and team_id and key_id and client_id:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": team_id,
                "sub": client_id,
                "aud": "https://appleid.apple.com",
                "iat": now,
                "exp": now + 60 * 60 * 24 * 20,
            },
            private_key.replace("\\n", "\n"),
            algorithm="ES256",
            headers={"kid": key_id, "typ": "JWT"},
        )
        return assertion
    secret = provider.client_secret()
    if not secret:
        raise OAuthError(
            "Apple sign-in is not configured on this server", http_status=503
        )
    return secret


async def fetch_profile(provider: OAuthProvider, tokens: dict) -> dict:
    """Normalise the provider's identity claims.

    Prefers the signed ``id_token`` (verified against the provider's JWKS) and
    falls back to the OIDC userinfo endpoint.
    """
    id_token = tokens.get("id_token")
    if id_token:
        claims = _decode_id_token(provider, id_token)
    elif provider.userinfo_url:
        claims = await _fetch_userinfo(provider, tokens["access_token"])
    else:
        raise OAuthError(f"{provider.label} did not return an identity token", 502)

    subject = claims.get("sub") or claims.get("id")
    if not subject:
        raise OAuthError(f"{provider.label} did not return a subject id", 502)
    email = (claims.get("email") or "").strip().lower() or None
    return {
        "subject": str(subject),
        "email": email,
        "email_verified": _as_bool(claims.get("email_verified")),
        "name": (claims.get("name") or claims.get("given_name") or "").strip() or None,
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def _decode_id_token(provider: OAuthProvider, id_token: str) -> dict:
    jwks_url = provider.jwks_endpoint()
    client_id = provider.client_id()
    if not jwks_url or not client_id:
        raise OAuthError(f"{provider.label} sign-in is not configured", 503)
    try:
        signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=client_id,
            options={"verify_exp": True},
        )
    except Exception as exc:  # any failure means the token is unverified
        raise OAuthError(f"{provider.label} identity token is invalid", 400) from exc
    if not isinstance(claims, dict):
        raise OAuthError(f"{provider.label} identity token is invalid", 400)
    return claims


async def _fetch_userinfo(provider: OAuthProvider, access_token: str) -> dict:
    if not provider.userinfo_url:
        raise OAuthError(f"{provider.label} has no userinfo endpoint", 502)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                provider.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        raise OAuthError(f"Could not reach {provider.label}: {exc}", 502) from exc
    if response.status_code >= 400:
        raise OAuthError(
            f"{provider.label} rejected the userinfo request", http_status=400
        )
    data = response.json()
    if not isinstance(data, dict):
        raise OAuthError(f"{provider.label} returned an invalid profile", 502)
    return data


# --------------------------------------------------------------------------- #
# Account linking
# --------------------------------------------------------------------------- #
async def upsert_oauth_user(
    session: AsyncSession, provider: OAuthProvider, profile: dict
) -> User:
    """Resolve the provider identity to a local user account.

    * known provider subject -> the linked user
    * verified e-mail that already exists -> link the provider to it
    * otherwise -> create a password-less account
    """
    subject = profile["subject"]
    account = (
        await session.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider.name,
                OAuthAccount.provider_user_id == subject,
            )
        )
    ).scalar_one_or_none()

    if account is not None:
        user = (
            await session.execute(select(User).where(User.id == account.user_id))
        ).scalar_one_or_none()
        if user is None:
            raise OAuthError("Linked account no longer exists", 500)
        account.email = profile.get("email") or account.email
        account.display_name = profile.get("name") or account.display_name
        await session.flush()
        return user

    email = profile.get("email")
    user: User | None = None
    if email and profile.get("email_verified"):
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

    if user is None:
        if not email:
            raise OAuthError(
                f"{provider.label} did not share a verified e-mail address", 400
            )
        user = User(
            email=email,
            hashed_password=security.unusable_password_hash(),
        )
        session.add(user)
        await session.flush()
        await collateral.get_or_create_account(session, user.id)

    session.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider.name,
            provider_user_id=subject,
            email=email,
            display_name=profile.get("name"),
        )
    )
    await session.flush()
    return user


# --------------------------------------------------------------------------- #
# One-time exchange codes
# --------------------------------------------------------------------------- #
async def create_exchange_code(
    session: AsyncSession, user_id: str, provider: str | None = None
) -> tuple[str, int]:
    """Mint a single-use code the browser can redeem for a JWT."""
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=EXCHANGE_CODE_TTL_SECONDS)
    session.add(
        AuthExchangeCode(
            code=code,
            user_id=user_id,
            provider=provider,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return code, EXCHANGE_CODE_TTL_SECONDS


async def consume_exchange_code(session: AsyncSession, code: str) -> User:
    """Redeem a one-time code exactly once and return the linked user."""
    row = (
        await session.execute(
            select(AuthExchangeCode).where(AuthExchangeCode.code == code)
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise OAuthError("Invalid or already used exchange code", 400)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise OAuthError("Exchange code expired", 400)
    row.used_at = datetime.now(UTC)
    user = (
        await session.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise OAuthError("Exchange code has no account", 400)
    await session.flush()
    return user
