"""Authentication endpoints: registration, login, and Web3 wallet sign-in."""
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import security
from app.db.session import get_async_session
from app.models.domain import User, WalletChallenge
from app.services import collateral

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class DexBuilderWalletRequest(BaseModel):
    wallet_address: str = Field(min_length=1, max_length=128)


class WalletChallengeRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)
    chain_id: int | None = 8453
    domain: str | None = Field(default=None, max_length=255)
    uri: str | None = Field(default=None, max_length=512)


class WalletChallengeResponse(BaseModel):
    challenge: str
    nonce: str
    expires_at: str


class WalletVerifyRequest(BaseModel):
    address: str = Field(min_length=42, max_length=42)
    signature: str = Field(min_length=64)
    nonce: str = Field(min_length=16, max_length=64)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "created_at": str(user.created_at),
        # Advisory for the client (the console only renders for admins);
        # the server remains the authority on every admin route.
        "is_admin": bool(getattr(user, "is_admin", False)),
        "dexbuilder_wallet": getattr(user, "dexbuilder_wallet", None),
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_async_session)):
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=body.email, hashed_password=security.hash_password(body.password))
    session.add(user)
    await session.flush()
    await collateral.get_or_create_account(session, user.id)
    token = security.create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=_user_payload(user))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_async_session)):
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or not security.verify_password_strict(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = security.create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=_user_payload(user))


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """Profile of the authenticated account."""
    return _user_payload(user)


@router.post("/dexbuilder-wallet")
async def set_dexbuilder_wallet(
    body: DexBuilderWalletRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Set the DexBuilder sub-user wallet address for the authenticated user."""
    user.dexbuilder_wallet = body.wallet_address
    await session.flush()
    return {"user_id": user.id, "dexbuilder_wallet": user.dexbuilder_wallet}


@router.post("/api-key")
async def rotate_api_key(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Issue (or rotate) an HMAC API key for algorithmic trading.

    The raw key is returned once. Only its digest is persisted, so it cannot
    be recovered from the database afterwards.
    """
    api_key, digest = security.generate_api_key()
    user.api_key = digest
    await session.flush()
    return {
        "api_key": api_key,
        "signature_scheme": "HMAC-SHA256",
        "message_format": "X-TIMESTAMP + METHOD + PATH + BODY",
        "headers": ["X-API-KEY", "X-TIMESTAMP", "X-SIGNATURE"],
    }


@router.post("/wallet/challenge", response_model=WalletChallengeResponse)
async def wallet_challenge(
    body: WalletChallengeRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    norm_address = body.address.strip().lower()
    if not norm_address.startswith("0x") or len(norm_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid EVM address format")

    nonce = secrets.token_hex(16)
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=5)
    iso_now = now.isoformat()

    canonical_url = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
    siwe_domain = os.environ.get("SIWE_DOMAIN", "").strip()
    if canonical_url and siwe_domain:
        domain = siwe_domain
        uri = canonical_url
    else:
        origin = (request.headers.get("origin") or "").strip().rstrip("/")
        if origin:
            parsed = urlparse(origin)
            domain = parsed.netloc or "dolymarket.com"
            uri = f"{parsed.scheme}://{domain}" if parsed.scheme and parsed.netloc else origin
        else:
            host = (request.headers.get("host") or request.url.netloc or "dolymarket.com").strip()
            scheme = request.url.scheme or "http"
            domain = host
            uri = f"{scheme}://{host}"

    if uri.startswith("https://"):
        message = (
            f"{domain} wants you to sign in with your Ethereum account:\n"
            f"{body.address.strip()}\n\n"
            f"Sign in to Dolymarket with your non-custodial crypto wallet.\n\n"
            f"URI: {uri}\n"
            f"Version: 1\n"
            f"Chain ID: {body.chain_id or 8453}\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {iso_now}"
        )
    else:
        # Local HTTP dev: avoid EIP-4361 header that some wallets (e.g. Gate Wallet)
        # strictly compare against https://<domain> and reject on http://localhost.
        message = (
            f"Sign in to Dolymarket\n"
            f"Address: {body.address.strip()}\n"
            f"Origin: {uri}\n"
            f"Chain ID: {body.chain_id or 8453}\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {iso_now}"
        )

    challenge_record = WalletChallenge(
        address=norm_address,
        nonce=nonce,
        message=message,
        expires_at=expires_at,
    )
    session.add(challenge_record)
    await session.flush()

    return WalletChallengeResponse(
        challenge=message,
        nonce=nonce,
        expires_at=expires_at.isoformat(),
    )


@router.post("/wallet/verify", response_model=TokenResponse)
async def wallet_verify(
    body: WalletVerifyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    norm_address = body.address.strip().lower()
    now = datetime.now(UTC)

    # 1. Fetch challenge
    res = await session.execute(
        select(WalletChallenge).where(
            WalletChallenge.nonce == body.nonce.strip(),
            WalletChallenge.address == norm_address,
        )
    )
    challenge_record = res.scalar_one_or_none()
    if not challenge_record:
        raise HTTPException(status_code=400, detail="Invalid or expired wallet challenge")

    # Handle timezone compatibility
    exp = challenge_record.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)

    if exp < now:
        await session.delete(challenge_record)
        await session.flush()
        raise HTTPException(status_code=400, detail="Wallet challenge has expired")

    # 2. Recover signer using eth_account
    try:
        signable_msg = encode_defunct(text=challenge_record.message)
        recovered = Account.recover_message(signable_msg, signature=body.signature.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid signature format: {exc}") from exc

    if recovered.lower() != norm_address:
        raise HTTPException(status_code=400, detail="Signature does not match wallet address")

    # Atomically consume challenge so concurrent verify calls cannot replay the nonce
    from sqlalchemy import delete

    consumed = await session.execute(
        delete(WalletChallenge).where(WalletChallenge.id == challenge_record.id)
    )
    if (consumed.rowcount or 0) != 1:
        raise HTTPException(status_code=400, detail="Wallet challenge already consumed")

    # 3. Lookup or auto-provision user
    user_res = await session.execute(
        select(User).where(User.dexbuilder_wallet == norm_address)
    )
    user = user_res.scalar_one_or_none()

    if not user:
        wallet_email = f"{norm_address}@wallet.dolymarket"
        email_res = await session.execute(select(User).where(User.email == wallet_email))
        user = email_res.scalar_one_or_none()

        if not user:
            user = User(
                email=wallet_email,
                hashed_password=security.unusable_password_hash(),
                dexbuilder_wallet=norm_address,
            )
            session.add(user)
            await session.flush()
            # Seed starting simulated trading collateral
            await collateral.get_or_create_account(session, user.id)

    token = security.create_access_token(user.id, user.email)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_payload(user),
    )
