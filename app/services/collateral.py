"""Collateral account service: deposits, locks, releases, fees and payouts."""
from decimal import ROUND_DOWN, Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import CollateralAccount, CollateralLedgerEntry, User

Q4 = Decimal("0.0001")


def q4(value) -> Decimal:
    return Decimal(str(value)).quantize(Q4, rounding=ROUND_DOWN)


async def get_or_create_account(
    session: AsyncSession, user_id: str, for_update: bool = False
) -> CollateralAccount:
    stmt = select(CollateralAccount).where(CollateralAccount.user_id == user_id)
    if for_update:
        # Row-level lock. PostgreSQL serialises concurrent balance mutations
        # for the same account; SQLite ignores FOR UPDATE but keeps the same
        # code path for hermetic tests.
        stmt = stmt.with_for_update()
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is None:
        account = CollateralAccount(user_id=user_id, balance=0, locked_balance=0)
        session.add(account)
        await session.flush()
    return account


async def deposit(session: AsyncSession, user: User, amount) -> CollateralAccount:
    amt = q4(amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive")
    account = await get_or_create_account(session, user.id, for_update=True)
    account.balance = q4(Decimal(str(account.balance)) + amt)
    await _ledger(session, account, "DEPOSIT", amt)
    return account


async def withdraw(
    session: AsyncSession, user: User, amount, for_update: bool = True
) -> CollateralAccount:
    amt = q4(amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be positive")
    account = await get_or_create_account(session, user.id, for_update=for_update)
    available = Decimal(str(account.balance)) - Decimal(str(account.locked_balance))
    if amt > available:
        raise HTTPException(status_code=400, detail="Insufficient available balance")
    account.balance = q4(Decimal(str(account.balance)) - amt)
    await _ledger(session, account, "WITHDRAWAL", -amt)
    return account


async def lock_for_buy(
    session: AsyncSession, user_id: str, cost: Decimal, for_update: bool = True
) -> CollateralAccount:
    """Lock ``cost`` collateral for a BUY order; 400 on insufficient funds.

    The account row is locked during the check-and-update so two concurrent
    orders cannot both observe the same available balance.
    """
    account = await get_or_create_account(session, user_id, for_update=for_update)
    available = Decimal(str(account.balance)) - Decimal(str(account.locked_balance))
    if cost > available:
        raise HTTPException(status_code=400, detail="Insufficient available balance")
    account.locked_balance = q4(Decimal(str(account.locked_balance)) + cost)
    await _ledger(session, account, "LOCK", cost)
    return account


async def release_lock(
    session: AsyncSession, account: CollateralAccount, amount: Decimal
) -> None:
    locked = Decimal(str(account.locked_balance))
    account.locked_balance = q4(max(Decimal(0), locked - amount))
    if amount > 0:
        await _ledger(session, account, "RELEASE", -amount)


def charge_fee_sync(account: CollateralAccount, fee: Decimal) -> None:
    """Deduct a trading fee from the unlocked balance (never goes negative)."""
    balance = Decimal(str(account.balance))
    account.balance = q4(max(Decimal(0), balance - fee))


async def charge_fee(
    session: AsyncSession, account: CollateralAccount, fee: Decimal
) -> None:
    """Deduct a trading fee from the unlocked balance (never goes negative)."""
    charge_fee_sync(account, fee)
    if fee > 0:
        await _ledger(session, account, "FEE", -fee)


async def credit_payout(
    session: AsyncSession, account: CollateralAccount, amount: Decimal, reference: str
) -> None:
    if amount > 0:
        account.balance = q4(Decimal(str(account.balance)) + amount)
        await _ledger(session, account, "PAYOUT", amount, reference)


async def _ledger(
    session: AsyncSession,
    account: CollateralAccount,
    kind: str,
    amount: Decimal,
    reference: str | None = None,
) -> None:
    session.add(
        CollateralLedgerEntry(
            account_id=account.id, kind=kind, amount=q4(amount), reference=reference
        )
    )


async def resolve_account(
    session: AsyncSession, user_id: str, for_update: bool = False
) -> CollateralAccount:
    return await get_or_create_account(session, user_id, for_update=for_update)


async def verified_deposit(
    session: AsyncSession, user: User, amount, tx_hash: str, chain_id: int
) -> CollateralAccount:
    """Credit USDC against a unique on-chain transaction reference (replay-proof)."""
    amt = q4(amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive")
    ref = f"onchain:{chain_id}:{tx_hash.strip().lower()}"
    existing = (
        await session.execute(
            select(CollateralLedgerEntry).where(CollateralLedgerEntry.reference == ref)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="On-chain deposit receipt already credited")
    account = await get_or_create_account(session, user.id, for_update=True)
    account.balance = q4(Decimal(str(account.balance)) + amt)
    try:
        await _ledger(session, account, "DEPOSIT", amt, reference=ref)
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="On-chain deposit receipt already credited"
        ) from exc
    return account


async def reconcile_account_ledger(session: AsyncSession, user_id: str) -> dict:
    """Verify double-entry ledger entries sum exactly to stored balance & locked_balance."""
    account = await get_or_create_account(session, user_id, for_update=False)
    entries = (
        await session.execute(
            select(CollateralLedgerEntry).where(CollateralLedgerEntry.account_id == account.id)
        )
    ).scalars().all()
    expected_bal = Decimal("0")
    expected_locked = Decimal("0")
    for e in entries:
        amt = Decimal(str(e.amount))
        if e.kind in ("DEPOSIT", "WITHDRAWAL", "FEE", "PAYOUT"):
            expected_bal += amt
        elif e.kind in ("LOCK", "RELEASE"):
            expected_locked += amt
    expected_bal = q4(expected_bal)
    expected_locked = q4(max(Decimal("0"), expected_locked))
    actual_bal = q4(account.balance or 0)
    actual_locked = q4(account.locked_balance or 0)
    return {
        "balanced": expected_bal == actual_bal and expected_locked == actual_locked,
        "expected_balance": format(expected_bal, "f"),
        "actual_balance": format(actual_bal, "f"),
        "expected_locked": format(expected_locked, "f"),
        "actual_locked": format(actual_locked, "f"),
        "entry_count": len(entries),
    }
