"""Authentication endpoints: registration and login."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.session import get_async_session
from app.models.domain import User
from app.services import collateral

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _user_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "created_at": str(user.created_at)}


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
