"""Collateral endpoints: balance queries, deposits, withdrawals, ledger."""
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import CollateralLedgerEntry, User
from app.services import collateral

router = APIRouter(prefix="/api/v1/collateral", tags=["collateral"])

_SEEN_DEPOSIT_KEYS: dict[str, dict] = {}
_MAX_IDEMPOTENCY_CACHE = 512


def _demo_collateral_enabled() -> bool:
    explicit = os.environ.get("ENABLE_DEMO_COLLATERAL", "").strip().lower()
    if explicit in ("0", "false", "no"):
        return False
    if explicit in ("1", "true", "yes"):
        return True
    return os.environ.get("APP_ENV", "").strip().lower() != "production"


class AmountRequest(BaseModel):
    # Decimal (not float) so binary rounding never touches money columns, with
    # a per-request cap: until a payment provider verifies real funds, the
    # deposit endpoint must not be able to mint unbounded balances.
    amount: Decimal = Field(gt=0, le=Decimal("100000"))

    @field_validator("amount")
    @classmethod
    def _check_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite number")
        return v


@router.get("/balance")
async def get_balance(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    account = await collateral.get_or_create_account(session, user.id)
    return {
        "user_id": user.id,
        "balance": float(account.balance or 0),
        "locked_balance": float(account.locked_balance or 0),
        "available": float(
            (account.balance or 0) - (account.locked_balance or 0)
        ),
        "currency": account.currency,
    }


@router.post("/deposit")
async def deposit(
    body: AmountRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    if not _demo_collateral_enabled():
        raise HTTPException(
            status_code=403,
            detail="DEMO_COLLATERAL_DISABLED: use on-chain DexBuilder deposit signing.",
        )
    cache_key = f"{user.id}:{idempotency_key}" if idempotency_key else None
    if cache_key and cache_key in _SEEN_DEPOSIT_KEYS:
        return _SEEN_DEPOSIT_KEYS[cache_key]

    account = await collateral.deposit(session, user, body.amount)
    payload = {
        "user_id": user.id,
        "balance": float(account.balance),
        "locked_balance": float(account.locked_balance),
        "currency": account.currency,
    }
    if cache_key:
        if len(_SEEN_DEPOSIT_KEYS) >= _MAX_IDEMPOTENCY_CACHE:
            _SEEN_DEPOSIT_KEYS.clear()
        _SEEN_DEPOSIT_KEYS[cache_key] = payload
    return payload


@router.post("/withdraw")
async def withdraw(
    body: AmountRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    account = await collateral.withdraw(session, user, body.amount)
    return {
        "user_id": user.id,
        "balance": float(account.balance),
        "locked_balance": float(account.locked_balance),
        "currency": account.currency,
    }


@router.get("/ledger")
async def ledger(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    account = await collateral.get_or_create_account(session, user.id)
    from sqlalchemy import select as _select

    entries = (
        await session.execute(
            _select(CollateralLedgerEntry)
            .where(CollateralLedgerEntry.account_id == account.id)
            .order_by(CollateralLedgerEntry.created_at.desc())
        )
    ).scalars().all()
    entries = list(entries)[:200]
    return {
        "entries": [
            {
                "id": e.id,
                "kind": e.kind,
                "amount": float(e.amount),
                "reference": e.reference,
                "created_at": str(e.created_at),
            }
            for e in entries[:200]
        ]
    }
