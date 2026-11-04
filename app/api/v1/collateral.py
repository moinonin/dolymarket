"""Collateral endpoints: balance queries, deposits, withdrawals, ledger."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import CollateralLedgerEntry, User
from app.services import collateral

router = APIRouter(prefix="/api/v1/collateral", tags=["collateral"])


class AmountRequest(BaseModel):
    amount: float = Field(gt=0)  # validated positive at schema level too


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
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    account = await collateral.deposit(session, user, body.amount)
    return {
        "user_id": user.id,
        "balance": float(account.balance),
        "locked_balance": float(account.locked_balance),
        "currency": account.currency,
    }


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
