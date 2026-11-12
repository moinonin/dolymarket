"""AGX (Algoxen) token utility endpoints.

Fourteen routes under ``/api/v1/agx``. AGX is complementary: these routes only
manage the optional token layer, and every response serialises amounts as
decimal strings so the wire format never carries binary floating point.
"""
from __future__ import annotations

import os
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.models.domain import (
    AgxDisputeStake,
    AgxRewardEpoch,
    AgxStake,
    AgxUnstakeCooldown,
    User,
)
from app.services import agx

router = APIRouter(prefix="/api/v1/agx", tags=["agx"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------
def _s(value) -> str:
    return format(agx.q18(value), "f")


def _balance_payload(row) -> dict:
    tier, discount = agx.tier_for(Decimal(row.staked_balance))
    return {
        "user_id": row.user_id,
        "balance": _s(row.balance),
        "staked_balance": _s(row.staked_balance),
        "locked_gating_balance": _s(row.locked_gating_balance),
        "locked_dispute_balance": _s(row.locked_dispute_balance),
        "pending_rewards": _s(row.pending_rewards),
        "last_reward_epoch": row.last_reward_epoch,
        "tier": tier,
        "tier_name": agx.TIER_NAMES[tier],
        "discount_rate": _s(discount),
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


def _stake_payload(record: AgxStake) -> dict:
    return {
        "id": record.id,
        "amount": _s(record.amount),
        "status": record.status,
        "locked_until": str(record.locked_until),
        "created_at": str(record.created_at) if record.created_at else None,
    }


def _cooldown_payload(record: AgxUnstakeCooldown) -> dict:
    return {
        "id": record.id,
        "stake_id": record.stake_id,
        "amount": _s(record.amount),
        "status": record.status,
        "cooldown_until": str(record.cooldown_until),
        "created_at": str(record.created_at) if record.created_at else None,
    }


def _dispute_payload(record: AgxDisputeStake) -> dict:
    return {
        "id": record.id,
        "market_id": record.market_id,
        "amount": _s(record.amount),
        "status": record.status,
        "created_at": str(record.created_at) if record.created_at else None,
        "resolved_at": str(record.resolved_at) if record.resolved_at else None,
        "treasury_address": agx.treasury_address(),
    }


def _epoch_payload(record: AgxRewardEpoch) -> dict:
    return {
        "id": record.id,
        "epoch_number": record.epoch_number,
        "total_fees_collected": _s(record.total_fees_collected),
        "total_staked_supply": _s(record.total_staked_supply),
        "reward_per_token": _s(record.reward_per_token),
        "creator_share": _s(record.creator_share),
        "staker_pool": _s(record.staker_pool),
        "creator_accruals": {
            user_id: _s(amount)
            for user_id, amount in (record.creator_accruals or {}).items()
        },
        "started_at": str(record.started_at) if record.started_at else None,
        "ended_at": str(record.ended_at) if record.ended_at else None,
        "distributed": bool(record.distributed),
    }


# ---------------------------------------------------------------------------
# Request bodies (decimal strings only)
# ---------------------------------------------------------------------------
class AmountBody(BaseModel):
    amount: StrictStr


class StakeIdBody(BaseModel):
    stake_id: StrictStr


class CooldownIdBody(BaseModel):
    cooldown_id: StrictStr


class DisputeBody(BaseModel):
    market_id: StrictStr
    amount: StrictStr | None = None


class SyncBody(BaseModel):
    verified_balance: StrictStr
    # Target account to reconcile. Defaults to the caller (useful for
    # self-service admin testing); the platform reconciler passes the user
    # whose on-chain balance was verified.
    user_id: StrictStr | None = None


class DistributeBody(BaseModel):
    epoch_number: int | None = None
    total_fees_collected: StrictStr | None = None


def _require_admin(user: User) -> None:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="AGX_FORBIDDEN")


# ---------------------------------------------------------------------------
# Staking lifecycle
# ---------------------------------------------------------------------------
@router.post("/stake", status_code=201)
async def stake_agx(
    body: AmountBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    record = await agx.stake(session, user.id, agx.parse_amount(body.amount))
    row = await agx.get_balance(session, user.id)
    return {
        "status": record.status,
        "stake": _stake_payload(record),
        "balance": _balance_payload(row),
    }


@router.post("/unstake")
async def unstake_agx(
    body: StakeIdBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    cooldown = await agx.unstake(session, user.id, body.stake_id)
    row = await agx.get_balance(session, user.id)
    return {
        "status": cooldown.status,
        "cooldown": _cooldown_payload(cooldown),
        "balance": _balance_payload(row),
    }


@router.post("/withdraw")
async def withdraw_agx(
    body: CooldownIdBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    cooldown = await agx.withdraw(session, user.id, body.cooldown_id)
    row = await agx.get_balance(session, user.id)
    return {
        "status": cooldown.status,
        "amount": _s(cooldown.amount),
        "balance": _balance_payload(row),
    }


@router.get("/balance")
async def get_agx_balance(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    row = await agx.get_balance(session, user.id)
    return _balance_payload(row)


@router.get("/stakes")
async def list_agx_stakes(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    stakes = list(
        (
            await session.execute(
                select(AgxStake)
                .where(AgxStake.user_id == user.id)
                .order_by(AgxStake.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    cooldowns = await agx.withdrawals(session, user.id)
    return {
        "stakes": [_stake_payload(s) for s in stakes],
        "cooldowns": [_cooldown_payload(c) for c in cooldowns],
    }


# ---------------------------------------------------------------------------
# Rewards
# ---------------------------------------------------------------------------
@router.post("/claim-rewards")
async def claim_agx_rewards(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    claimed, row = await agx.claim_rewards(session, user.id)
    return {"claimed": _s(claimed), "balance": _balance_payload(row)}


@router.get("/rewards/history")
async def agx_reward_history(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    entries = await agx.reward_history(session, user.id)
    total = sum((Decimal(e.amount) for e in entries), Decimal(0))
    return {
        "rewards": [
            {
                "id": e.id,
                "amount": _s(e.amount),
                "balance_after": _s(e.balance_after),
                "reference_id": e.reference_id,
                "created_at": str(e.created_at) if e.created_at else None,
            }
            for e in entries
        ],
        "total": _s(total),
    }


@router.get("/tiers")
async def agx_tiers(
    session: AsyncSession = Depends(get_async_session),
):
    stats = await agx.staker_stats(session)
    return {
        "tiers": [
            {
                "tier": row["tier"],
                "name": row["name"],
                "min_staked": _s(row["min_staked"]),
                "discount_rate": _s(row["discount"]),
            }
            for row in agx.tier_ladder()
        ],
        "total_staked": _s(stats["total_staked"]),
        "staker_count": stats["staker_count"],
    }


# ---------------------------------------------------------------------------
# Dispute bonds
# ---------------------------------------------------------------------------
@router.post("/dispute-stake", status_code=201)
async def stake_agx_dispute(
    body: DisputeBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    amount = agx.parse_amount(body.amount) if body.amount is not None else None
    bond = await agx.stake_dispute(session, user.id, body.market_id, amount)
    row = await agx.get_balance(session, user.id)
    return {"dispute": _dispute_payload(bond), "balance": _balance_payload(row)}


@router.get("/dispute-stakes")
async def list_agx_disputes(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    bonds = await agx.dispute_stakes(session, user.id)
    return {"disputes": [_dispute_payload(b) for b in bonds]}


# ---------------------------------------------------------------------------
# On-chain reconciliation
# ---------------------------------------------------------------------------
@router.post("/sync-balance")
async def sync_agx_balance(
    body: SyncBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    # Only the platform reconciler may attest on-chain balances; otherwise any
    # caller could mint spendable AGX by asserting a number.
    _require_admin(user)
    target_id = body.user_id or user.id
    if body.user_id:
        target = (
            await session.execute(select(User).where(User.id == body.user_id))
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    row, credited = await agx.sync_balance(
        session, target_id, agx.parse_amount(body.verified_balance)
    )
    return {"user_id": target_id, "credited": _s(credited), "balance": _balance_payload(row)}


@router.get("/stats")
async def agx_stats(session: AsyncSession = Depends(get_async_session)):
    stats = await agx.staker_stats(session)
    return {
        "chain_id": int(os.environ.get("AGX_CHAIN_ID", "42161") or 42161),
        "token_symbol": "AGX",
        "token_decimals": 18,
        "treasury_address": agx.treasury_address(),
        "total_staked": _s(stats["total_staked"]),
        "total_spendable": _s(stats["total_spendable"]),
        "total_gating_locked": _s(stats["total_gating_locked"]),
        "total_dispute_locked": _s(stats["total_dispute_locked"]),
        "staker_count": stats["staker_count"],
        "epoch_count": stats["epoch_count"],
        "distributed_staker_pool": _s(stats["distributed_staker_pool"]),
    }


# ---------------------------------------------------------------------------
# Reward epochs
# ---------------------------------------------------------------------------
@router.post("/epochs/distribute")
async def distribute_agx_epoch(
    body: DistributeBody | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_admin(user)
    payload = body or DistributeBody()
    total = (
        agx.parse_amount(payload.total_fees_collected)
        if payload.total_fees_collected is not None
        else None
    )
    epoch, rewarded = await agx.distribute_epoch(
        session, epoch_number=payload.epoch_number, total_fees_collected=total
    )
    return {"epoch": _epoch_payload(epoch), "rewarded_stakers": rewarded}


@router.get("/epochs")
async def list_agx_epochs(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
):
    epochs = list(
        (
            await session.execute(
                select(AgxRewardEpoch)
                .order_by(AgxRewardEpoch.epoch_number.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {"epochs": [_epoch_payload(e) for e in epochs]}
