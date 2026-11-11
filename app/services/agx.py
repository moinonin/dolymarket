"""AGX (Algoxen) token utility service.

AGX is a **complementary** utility token. Nothing in this module is required
for trading, collateral, settlement or payout redemption: a user with no
``AgxBalance`` row is Tier 0 and pays the existing base fee unchanged.

Accounting model
----------------
``AgxBalance`` keeps four buckets -- spendable, staked, gating-locked and
dispute-locked -- plus ``pending_rewards``. Every mutation of the *spendable*
bucket appends one immutable :class:`~app.models.domain.AgxLedger` row whose
``amount`` is the signed change and whose ``balance_after`` is the spendable
balance afterwards. Moves between buckets that do not touch the spendable
balance (UNSTAKE_COOLDOWN, SLASH) still emit a row with ``amount == 0`` so the
audit trail has no gaps.

All token arithmetic uses :class:`decimal.Decimal` quantized to 18 places with
``ROUND_DOWN``. Binary floating point is never used for token math.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    AgxBalance,
    AgxDeskStake,
    AgxDisputeStake,
    AgxLedger,
    AgxMarketStake,
    AgxRewardEpoch,
    AgxStake,
    AgxUnstakeCooldown,
    Market,
)

Q18 = Decimal("0.000000000000000001")
ZERO = Decimal(0)
ONE = Decimal(1)


class AgxError(Exception):
    """Deterministic domain failure carrying its HTTP mapping.

    The router layer (and ``app.main``) convert this into an HTTP response with
    the stable ``UPPER_SNAKE`` code in ``detail``.
    """

    def __init__(self, code: str, status_code: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def q18(value) -> Decimal:
    """Quantize a token amount to 18 decimal places, rounding down."""
    try:
        return Decimal(value).quantize(Q18, rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError) as exc:  # pragma: no cover
        raise AgxError("AGX_INVALID_AMOUNT", 422) from exc


def parse_amount(value) -> Decimal:
    """Parse a JSON-boundary decimal string, rejecting anything lossy."""
    if isinstance(value, bool):
        raise AgxError("AGX_INVALID_AMOUNT", 422)
    if isinstance(value, float):
        # JSON numbers arrive as floats; refuse them so precision can never be
        # silently lost. Clients must send decimal strings, as contracted.
        raise AgxError("AGX_INVALID_AMOUNT", 422)
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise AgxError("AGX_INVALID_AMOUNT", 422)
    if not parsed.is_finite():
        raise AgxError("AGX_INVALID_AMOUNT", 422)
    return q18(parsed)


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat stored values as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _env_decimal(name: str, default: str) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return Decimal(default)
    try:
        return Decimal(raw.strip())
    except InvalidOperation:
        return Decimal(default)


def _env_int(name: str, default: str) -> int:
    raw = os.environ.get(name)
    try:
        return int((raw or default).strip())
    except (ValueError, AttributeError):
        return int(default)


def min_stake() -> Decimal:
    return _env_decimal("AGX_MIN_STAKE", "1")


def stake_lock_days() -> int:
    return _env_int("AGX_MIN_STAKE_LOCK_DAYS", "7")


def unstake_cooldown_days() -> int:
    return _env_int("AGX_UNSTAKE_COOLDOWN_DAYS", "3")


def dispute_min_stake() -> Decimal:
    return _env_decimal("AGX_DISPUTE_MIN_STAKE", "100")


def dispute_reward_pct() -> Decimal:
    return _env_decimal("AGX_DISPUTE_REWARD_PCT", "0.20")


def desk_min_stake() -> Decimal:
    return _env_decimal("AGX_DESK_MIN_STAKE", "500")


def market_min_stake() -> Decimal:
    return _env_decimal("AGX_MARKET_MIN_STAKE", "1000")


def creator_fee_share() -> Decimal:
    return _env_decimal("AGX_CREATOR_FEE_SHARE", "0.40")


def staker_fee_share() -> Decimal:
    return _env_decimal("AGX_STAKER_FEE_SHARE", "0.60")


def treasury_address() -> str:
    return os.environ.get("AGX_TREASURY_ADDRESS", "0x0000000000000000000000000000000000007ea5")


# Tier ladder: (minimum staked AGX, tier id, relative fee discount).
def _ladder() -> tuple[tuple[Decimal, str, Decimal], ...]:
    return (
        (Decimal("5000"), "3", _env_decimal("AGX_FEE_DISCOUNT_RATE_3", "0.15")),
        (Decimal("1000"), "2", _env_decimal("AGX_FEE_DISCOUNT_RATE_2", "0.10")),
        (Decimal("100"), "1", _env_decimal("AGX_FEE_DISCOUNT_RATE_1", "0.05")),
    )


TIER_NAMES = {"0": "None", "1": "Bronze", "2": "Silver", "3": "Gold"}


def tier_for(staked: Decimal) -> tuple[str, Decimal]:
    """Return ``(tier, discount)`` for a staked amount."""
    amount = Decimal(staked)
    for floor, tier, discount in _ladder():
        if amount >= floor:
            return tier, discount
    return "0", ZERO


def tier_ladder() -> list[dict]:
    ladder = sorted(_ladder(), key=lambda row: row[0])
    rows = [{"tier": "0", "name": TIER_NAMES["0"], "min_staked": ZERO, "discount": ZERO}]
    for floor, tier, discount in ladder:
        rows.append(
            {
                "tier": tier,
                "name": TIER_NAMES[tier],
                "min_staked": floor,
                "discount": discount,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Balance access
# ---------------------------------------------------------------------------
async def peek_balance(session: AsyncSession, user_id: str) -> AgxBalance | None:
    """Read the balance row without creating one (used by read-only paths)."""
    return (
        await session.execute(
            select(AgxBalance).where(AgxBalance.user_id == user_id)
        )
    ).scalar_one_or_none()


async def get_balance(
    session: AsyncSession, user_id: str, for_update: bool = False
) -> AgxBalance:
    """Return the caller's balance row, creating an all-zero row on first use."""
    stmt = select(AgxBalance).where(AgxBalance.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = AgxBalance(
            user_id=user_id,
            balance=ZERO,
            staked_balance=ZERO,
            locked_gating_balance=ZERO,
            locked_dispute_balance=ZERO,
            pending_rewards=ZERO,
        )
        session.add(row)
        await session.flush()
    return row


def custody_total(row: AgxBalance) -> Decimal:
    """Total AGX still held by the platform for this user."""
    return (
        Decimal(row.balance)
        + Decimal(row.staked_balance)
        + Decimal(row.locked_gating_balance)
        + Decimal(row.locked_dispute_balance)
    )


async def get_tier(session: AsyncSession, user_id: str) -> str:
    row = await peek_balance(session, user_id)
    if row is None:
        return "0"
    return tier_for(Decimal(row.staked_balance))[0]


async def apply_fee_discount(
    user_id: str, base_fee: Decimal, session: AsyncSession | None = None
) -> Decimal:
    """Apply the staker discount to a taker fee.

    A missing balance row, a zero stake, an unconfigured sync or any storage
    failure degrades to the untouched base fee. This hook must never be able to
    break order execution.
    """
    base = q18(base_fee)
    if session is None:
        return base
    try:
        row = await peek_balance(session, user_id)
    except Exception:  # pragma: no cover - defensive: AGX must never block trading
        return base
    if row is None:
        return base
    _, discount = tier_for(Decimal(row.staked_balance))
    if discount == 0:
        return base
    return q18(base * (ONE - discount))


def _ledger(
    session: AsyncSession,
    user_id: str,
    kind: str,
    amount: Decimal,
    balance_after: Decimal,
    reference_id: str | None = None,
) -> AgxLedger:
    entry = AgxLedger(
        user_id=user_id,
        kind=kind,
        amount=q18(amount),
        balance_after=q18(balance_after),
        reference_id=reference_id,
    )
    session.add(entry)
    return entry


def _owned(record, user_id: str, not_found: str) -> None:
    if record is None:
        raise AgxError(not_found, 404)
    if record.user_id != user_id:
        raise AgxError("AGX_FORBIDDEN", 403)


# ---------------------------------------------------------------------------
# Staking lifecycle
# ---------------------------------------------------------------------------
async def stake(session: AsyncSession, user_id: str, amount) -> AgxStake:
    amt = q18(amount)
    minimum = min_stake()
    if amt < minimum:
        raise AgxError("AGX_STAKE_BELOW_MINIMUM", 422)

    row = await get_balance(session, user_id, for_update=True)
    if Decimal(row.balance) < amt:
        raise AgxError("AGX_INSUFFICIENT_BALANCE", 409)

    row.balance = q18(Decimal(row.balance) - amt)
    row.staked_balance = q18(Decimal(row.staked_balance) + amt)

    record = AgxStake(
        user_id=user_id,
        amount=amt,
        locked_until=now_utc() + timedelta(days=stake_lock_days()),
        status="ACTIVE",
    )
    session.add(record)
    await session.flush()
    _ledger(session, user_id, "STAKE", -amt, row.balance, record.id)
    return record


async def unstake(session: AsyncSession, user_id: str, stake_id: str) -> AgxUnstakeCooldown:
    record = await session.get(AgxStake, stake_id, with_for_update=True)
    _owned(record, user_id, "AGX_STAKE_NOT_FOUND")
    if record.status != "ACTIVE":
        raise AgxError("AGX_STAKE_NOT_ACTIVE", 409)
    if as_utc(record.locked_until) > now_utc():
        raise AgxError("AGX_STAKE_LOCKED", 422)

    row = await get_balance(session, user_id, for_update=True)
    amount = q18(record.amount)
    row.staked_balance = q18(Decimal(row.staked_balance) - amount)
    record.status = "COOLDOWN"

    cooldown = AgxUnstakeCooldown(
        stake_id=record.id,
        user_id=user_id,
        amount=amount,
        cooldown_until=now_utc() + timedelta(days=unstake_cooldown_days()),
        status="PENDING",
    )
    session.add(cooldown)
    await session.flush()
    _ledger(session, user_id, "UNSTAKE_COOLDOWN", ZERO, row.balance, cooldown.id)
    return cooldown


async def withdraw(
    session: AsyncSession, user_id: str, cooldown_id: str
) -> AgxUnstakeCooldown:
    cooldown = await session.get(
        AgxUnstakeCooldown, cooldown_id, with_for_update=True
    )
    _owned(cooldown, user_id, "AGX_COOLDOWN_NOT_FOUND")
    if cooldown.status != "PENDING":
        raise AgxError("AGX_COOLDOWN_NOT_PENDING", 409)
    if as_utc(cooldown.cooldown_until) > now_utc():
        raise AgxError("AGX_COOLDOWN_ACTIVE", 422)

    row = await get_balance(session, user_id, for_update=True)
    amount = q18(cooldown.amount)
    cooldown.status = "COMPLETED"
    stake = await session.get(AgxStake, cooldown.stake_id, with_for_update=True)
    if stake is not None:
        stake.status = "WITHDRAWN"
    row.balance = q18(Decimal(row.balance) + amount)
    _ledger(session, user_id, "WITHDRAW_STAKE", amount, row.balance, cooldown.id)
    return cooldown


async def withdrawals(session: AsyncSession, user_id: str) -> list[AgxUnstakeCooldown]:
    return list(
        (
            await session.execute(
                select(AgxUnstakeCooldown)
                .where(AgxUnstakeCooldown.user_id == user_id)
                .order_by(AgxUnstakeCooldown.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Dispute bonds
# ---------------------------------------------------------------------------
async def stake_dispute(
    session: AsyncSession, user_id: str, market_id: str, amount=None
) -> AgxDisputeStake:
    market = await session.get(Market, market_id)
    if market is None:
        raise AgxError("AGX_MARKET_NOT_FOUND", 404)

    minimum = dispute_min_stake()
    amt = minimum if amount is None else q18(amount)
    if amt < minimum:
        raise AgxError("AGX_DISPUTE_BELOW_MINIMUM", 422)

    active = (
        await session.execute(
            select(AgxDisputeStake).where(
                AgxDisputeStake.user_id == user_id,
                AgxDisputeStake.market_id == market_id,
                AgxDisputeStake.status == "LOCKED",
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise AgxError("AGX_DISPUTE_EXISTS", 409)

    row = await get_balance(session, user_id, for_update=True)
    if Decimal(row.balance) < amt:
        raise AgxError("AGX_INSUFFICIENT_BALANCE", 409)

    row.balance = q18(Decimal(row.balance) - amt)
    row.locked_dispute_balance = q18(Decimal(row.locked_dispute_balance) + amt)

    bond = AgxDisputeStake(
        user_id=user_id, market_id=market_id, amount=amt, status="LOCKED"
    )
    session.add(bond)
    await session.flush()
    _ledger(session, user_id, "DISPUTE_LOCK", -amt, row.balance, bond.id)
    return bond


async def resolve_dispute(
    session: AsyncSession, dispute_id: str, upheld: bool
) -> AgxDisputeStake:
    bond = await session.get(AgxDisputeStake, dispute_id, with_for_update=True)
    if bond is None:
        raise AgxError("AGX_DISPUTE_NOT_FOUND", 404)
    if bond.status != "LOCKED":
        raise AgxError("AGX_DISPUTE_NOT_LOCKED", 409)

    row = await get_balance(session, bond.user_id, for_update=True)
    amount = q18(bond.amount)
    row.locked_dispute_balance = q18(
        Decimal(row.locked_dispute_balance) - amount
    )
    bond.resolved_at = now_utc()

    if upheld:
        bonus = q18(amount * dispute_reward_pct())
        row.balance = q18(Decimal(row.balance) + amount)
        _ledger(session, bond.user_id, "DISPUTE_RETURN", amount, row.balance, bond.id)
        row.balance = q18(Decimal(row.balance) + bonus)
        _ledger(session, bond.user_id, "DISPUTE_REWARD", bonus, row.balance, bond.id)
        bond.status = "RETURNED"
    else:
        # The bonded AGX leaves the platform's user custody for the protocol
        # treasury address; the ledger row records the destination.
        _ledger(
            session,
            bond.user_id,
            "SLASH",
            ZERO,
            row.balance,
            f"{bond.id}:{treasury_address()}",
        )
        bond.status = "SLASHED"
    await session.flush()
    return bond


async def dispute_stakes(
    session: AsyncSession, user_id: str | None = None
) -> list[AgxDisputeStake]:
    stmt = select(AgxDisputeStake).order_by(AgxDisputeStake.created_at.desc())
    if user_id is not None:
        stmt = stmt.where(AgxDisputeStake.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Feature gating bonds
# ---------------------------------------------------------------------------
async def _lock_gating(
    session: AsyncSession,
    user_id: str,
    target_id: str,
    kind: str,
    amount,
) -> AgxDeskStake | AgxMarketStake:
    model = AgxDeskStake if kind == "DESK" else AgxMarketStake
    id_column = "desk_id" if kind == "DESK" else "market_id"
    existing = (
        await session.execute(
            select(model).where(
                model.user_id == user_id,
                getattr(model, id_column) == target_id,
                model.status == "LOCKED",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    minimum = desk_min_stake() if kind == "DESK" else market_min_stake()
    amt = minimum if amount is None else q18(amount)
    if amt < minimum:
        raise AgxError("AGX_GATE_BELOW_MINIMUM", 422)

    row = await get_balance(session, user_id, for_update=True)
    if Decimal(row.balance) < amt:
        raise AgxError("AGX_INSUFFICIENT_GATE", 409)

    row.balance = q18(Decimal(row.balance) - amt)
    row.locked_gating_balance = q18(Decimal(row.locked_gating_balance) + amt)
    record = model(user_id=user_id, amount=amt, status="LOCKED", **{id_column: target_id})
    session.add(record)
    await session.flush()
    _ledger(session, user_id, "GATING_LOCK", -amt, row.balance, record.id)
    return record


async def _release_gating(
    session: AsyncSession, user_id: str, target_id: str, kind: str
) -> AgxDeskStake | AgxMarketStake | None:
    model = AgxDeskStake if kind == "DESK" else AgxMarketStake
    id_column = "desk_id" if kind == "DESK" else "market_id"
    record = (
        await session.execute(
            select(model).where(
                model.user_id == user_id,
                getattr(model, id_column) == target_id,
                model.status == "LOCKED",
            )
        )
    ).scalar_one_or_none()
    if record is None:
        return None

    row = await get_balance(session, user_id, for_update=True)
    amount = q18(record.amount)
    record.status = "RELEASED"
    record.released_at = now_utc()
    row.locked_gating_balance = q18(Decimal(row.locked_gating_balance) - amount)
    row.balance = q18(Decimal(row.balance) + amount)
    _ledger(session, user_id, "GATING_RELEASE", amount, row.balance, record.id)
    return record


async def lock_desk_gating(
    session: AsyncSession, user_id: str, desk_id: str, amount=None
) -> AgxDeskStake:
    return await _lock_gating(session, user_id, desk_id, "DESK", amount)


async def release_desk_gating(
    session: AsyncSession, user_id: str, desk_id: str
) -> AgxDeskStake | None:
    return await _release_gating(session, user_id, desk_id, "DESK")


async def lock_market_gating(
    session: AsyncSession, user_id: str, market_id: str, amount=None
) -> AgxMarketStake:
    return await _lock_gating(session, user_id, market_id, "MARKET", amount)


async def release_market_gating(
    session: AsyncSession, user_id: str, market_id: str
) -> AgxMarketStake | None:
    return await _release_gating(session, user_id, market_id, "MARKET")


async def ensure_desk_bond(
    session: AsyncSession, user_id: str, desk_id: str
) -> AgxDeskStake:
    """Bind a Pro Desk to the 500 AGX activation stake, auto-locking if possible."""
    return await lock_desk_gating(session, user_id, desk_id, None)


async def ensure_market_bond(
    session: AsyncSession, user_id: str, market_id: str
) -> AgxMarketStake:
    """Bind an official market to the 1,000 AGX creation stake."""
    return await lock_market_gating(session, user_id, market_id, None)


# ---------------------------------------------------------------------------
# On-chain reconciliation
# ---------------------------------------------------------------------------
async def sync_balance(
    session: AsyncSession, user_id: str, verified_balance
) -> tuple[AgxBalance, Decimal]:
    """Reconcile a verified on-chain balance with the off-chain ledger.

    ``verified_balance`` is the total confirmed on-chain AGX for the user. Only
    the net positive delta over prior verified deposits is credited, so repeated
    syncs are idempotent and the local spendable balance can never exceed
    cumulative verified deposits.
    """
    target = q18(verified_balance)
    if target < 0:
        raise AgxError("AGX_INVALID_AMOUNT", 422)

    verified_total = (
        await session.execute(
            select(func.coalesce(func.sum(AgxLedger.amount), 0)).where(
                AgxLedger.user_id == user_id, AgxLedger.kind == "DEPOSIT"
            )
        )
    ).scalar_one()
    already_verified = q18(verified_total or 0)
    delta = q18(target - already_verified)

    row = await get_balance(session, user_id, for_update=True)
    if delta <= 0:
        return row, ZERO

    row.balance = q18(Decimal(row.balance) + delta)
    _ledger(session, user_id, "DEPOSIT", delta, row.balance, "onchain-sync")
    return row, delta


# ---------------------------------------------------------------------------
# Reward epochs
# ---------------------------------------------------------------------------
async def _next_epoch_number(session: AsyncSession) -> int:
    current = (
        await session.execute(select(func.max(AgxRewardEpoch.epoch_number)))
    ).scalar_one()
    return int(current or 0) + 1


async def current_epoch(session: AsyncSession, create: bool = True) -> AgxRewardEpoch | None:
    epoch = (
        await session.execute(
            select(AgxRewardEpoch)
            .where(AgxRewardEpoch.distributed.is_(False))
            .order_by(AgxRewardEpoch.epoch_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if epoch is None and create:
        epoch = AgxRewardEpoch(
            epoch_number=await _next_epoch_number(session),
            total_fees_collected=ZERO,
            total_staked_supply=ZERO,
            reward_per_token=ZERO,
            creator_accruals={},
            distributed=False,
        )
        session.add(epoch)
        await session.flush()
    return epoch


async def record_fee(
    session: AsyncSession,
    amount,
    creator_user_id: str | None = None,
) -> AgxRewardEpoch | None:
    """Accumulate a collected trading fee into the open epoch.

    Called from the fill path. The creator weight is recorded so the 40 percent
    creator share stays attributable; the 60 percent staker pool is split by
    staked balance at distribution time.
    """
    amt = q18(amount)
    if amt <= 0:
        return None
    epoch = await current_epoch(session, create=True)
    epoch.total_fees_collected = q18(Decimal(epoch.total_fees_collected) + amt)
    if creator_user_id:
        accruals = dict(epoch.creator_accruals or {})
        accrued = q18(Decimal(accruals.get(creator_user_id, "0")) + amt)
        accruals[creator_user_id] = format(accrued, "f")
        epoch.creator_accruals = accruals
    return epoch


async def distribute_epoch(
    session: AsyncSession,
    epoch_number: int | None = None,
    total_fees_collected=None,
) -> tuple[AgxRewardEpoch, int]:
    """Distribute one epoch: 40 percent to creators, 60 percent to stakers.

    Idempotency is enforced by the ``distributed`` flag; a repeat raises
    ``AGX_EPOCH_ALREADY_DISTRIBUTED`` (HTTP 409) with no ledger writes.
    """
    if epoch_number is None:
        epoch = await current_epoch(session, create=True)
    else:
        epoch = (
            await session.execute(
                select(AgxRewardEpoch)
                .where(AgxRewardEpoch.epoch_number == epoch_number)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if epoch is None:
            raise AgxError("AGX_EPOCH_NOT_FOUND", 404)

    if epoch.distributed:
        raise AgxError("AGX_EPOCH_ALREADY_DISTRIBUTED", 409)

    if total_fees_collected is not None:
        epoch.total_fees_collected = q18(total_fees_collected)

    total = q18(epoch.total_fees_collected)
    supply = q18(
        (
            await session.execute(
                select(func.coalesce(func.sum(AgxBalance.staked_balance), 0))
            )
        ).scalar_one()
        or 0
    )

    share = creator_fee_share()
    creator_share = q18(total * share)
    staker_pool = q18(total - creator_share)

    epoch.total_staked_supply = supply
    epoch.creator_share = creator_share
    epoch.staker_pool = staker_pool
    epoch.reward_per_token = (
        q18(staker_pool / supply) if supply > 0 else ZERO
    )

    rewarded = 0
    if supply > 0 and staker_pool > 0:
        stakers = (
            await session.execute(
                select(AgxBalance)
                .where(AgxBalance.staked_balance > 0)
                .with_for_update()
            )
        ).scalars().all()
        for staker in stakers:
            stake_amount = q18(staker.staked_balance)
            reward = q18(staker_pool * stake_amount / supply)
            if reward <= 0:
                continue
            staker.pending_rewards = q18(Decimal(staker.pending_rewards) + reward)
            staker.last_reward_epoch = str(epoch.epoch_number)
            rewarded += 1

    accruals = dict(epoch.creator_accruals or {})
    weight_total = sum((Decimal(str(w)) for w in accruals.values()), ZERO)
    if creator_share > 0 and weight_total > 0:
        from app.services import collateral  # local import avoids a cycle

        for creator_id, weight in accruals.items():
            portion = q18(creator_share * Decimal(str(weight)) / weight_total)
            if portion <= 0:
                continue
            account = await collateral.get_or_create_account(
                session, creator_id, for_update=True
            )
            await collateral.credit_payout(
                session, account, portion, f"agx-epoch-{epoch.epoch_number}"
            )

    epoch.distributed = True
    epoch.ended_at = now_utc()
    await session.flush()
    return epoch, rewarded


async def claim_rewards(
    session: AsyncSession, user_id: str
) -> tuple[Decimal, AgxBalance]:
    """Move accrued pending rewards into the spendable balance."""
    row = await get_balance(session, user_id, for_update=True)
    amount = q18(row.pending_rewards)
    if amount <= 0:
        return ZERO, row
    row.pending_rewards = ZERO
    row.balance = q18(Decimal(row.balance) + amount)
    _ledger(
        session,
        user_id,
        "FEE_REWARD",
        amount,
        row.balance,
        f"epoch:{row.last_reward_epoch or 'accrual'}",
    )
    return amount, row


async def reward_history(session: AsyncSession, user_id: str) -> list[AgxLedger]:
    return list(
        (
            await session.execute(
                select(AgxLedger)
                .where(AgxLedger.user_id == user_id, AgxLedger.kind == "FEE_REWARD")
                .order_by(AgxLedger.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def staker_stats(session: AsyncSession) -> dict:
    """Aggregate protocol figures for the public stats route."""
    total_staked = q18(
        (await session.execute(select(func.coalesce(func.sum(AgxBalance.staked_balance), 0)))).scalar_one()
        or 0
    )
    total_spendable = q18(
        (await session.execute(select(func.coalesce(func.sum(AgxBalance.balance), 0)))).scalar_one()
        or 0
    )
    total_gating = q18(
        (await session.execute(select(func.coalesce(func.sum(AgxBalance.locked_gating_balance), 0)))).scalar_one()
        or 0
    )
    total_dispute = q18(
        (await session.execute(select(func.coalesce(func.sum(AgxBalance.locked_dispute_balance), 0)))).scalar_one()
        or 0
    )
    staker_count = int(
        (
            await session.execute(
                select(func.count()).select_from(AgxBalance).where(AgxBalance.staked_balance > 0)
            )
        ).scalar_one()
        or 0
    )
    epoch_count = int(
        (await session.execute(select(func.count()).select_from(AgxRewardEpoch))).scalar_one() or 0
    )
    distributed_total = q18(
        (
            await session.execute(
                select(func.coalesce(func.sum(AgxRewardEpoch.staker_pool), 0)).where(
                    AgxRewardEpoch.distributed.is_(True)
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "total_staked": total_staked,
        "total_spendable": total_spendable,
        "total_gating_locked": total_gating,
        "total_dispute_locked": total_dispute,
        "staker_count": staker_count,
        "epoch_count": epoch_count,
        "distributed_staker_pool": distributed_total,
    }


__all__ = [
    "AgxError",
    "apply_fee_discount",
    "claim_rewards",
    "current_epoch",
    "custody_total",
    "distribute_epoch",
    "dispute_stakes",
    "ensure_desk_bond",
    "ensure_market_bond",
    "get_balance",
    "get_tier",
    "lock_desk_gating",
    "lock_market_gating",
    "min_stake",
    "now_utc",
    "parse_amount",
    "peek_balance",
    "q18",
    "record_fee",
    "release_desk_gating",
    "release_market_gating",
    "resolve_dispute",
    "reward_history",
    "stake",
    "stake_dispute",
    "staker_stats",
    "sync_balance",
    "tier_for",
    "tier_ladder",
    "unstake",
    "withdraw",
    "withdrawals",
]
