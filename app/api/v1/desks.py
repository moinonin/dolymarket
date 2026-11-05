"""Pro Desks: non-custodial copy trading endpoints."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_session
from app.engine.clob import MatchingEngine, OrderRejected
from app.models.domain import (
    CopyJob,
    Desk,
    DeskFollower,
    DeskPosition,
    Market,
    Order,
    OutcomeToken,
    Position,
    TradeFill,
    User,
)
from app.services import collateral, copy_engine, desk_track_record

router = APIRouter(prefix="/api/v1", tags=["desks"])


def _enabled() -> bool:
    return os.environ.get("COPY_TRADING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _ensure_enabled():
    if not _enabled():
        raise HTTPException(status_code=404, detail="Copy trading is disabled")


def _q4(v):
    return collateral.q4(v)


def _min_closed_positions() -> int:
    try:
        return int(os.environ.get("DESK_MIN_CLOSED_POSITIONS", "10").strip() or 10)
    except ValueError:
        return 10


def _min_days_active() -> int:
    try:
        return int(os.environ.get("DESK_MIN_DAYS_ACTIVE", "14").strip() or 14)
    except ValueError:
        return 14


class CreateDeskRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9-]+$")
    description: str | None = None


class UpdateDeskRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class FollowRequest(BaseModel):
    copy_ratio: float | None = None
    per_market_cap_usdc: float | None = None
    max_per_market_pct: float | None = None
    max_total_pct: float | None = None
    status: str | None = None


def _desk_payload(desk: Desk, record: dict | None = None) -> dict:
    return {
        "id": desk.id,
        "owner_user_id": desk.owner_user_id,
        "name": desk.name,
        "slug": desk.slug,
        "description": desk.description,
        "status": desk.status,
        "review_note": desk.review_note,
        "created_at": str(desk.created_at),
        "activated_at": str(desk.activated_at) if desk.activated_at else None,
        "suspended_at": str(desk.suspended_at) if desk.suspended_at else None,
        "archived_at": str(desk.archived_at) if desk.archived_at else None,
        "track_record": record or {},
    }


async def _get_desk(session: AsyncSession, desk_id: str) -> Desk:
    desk = (await session.execute(select(Desk).where(Desk.id == desk_id))).scalar_one_or_none()
    if desk is None:
        raise HTTPException(status_code=404, detail="Desk not found")
    return desk


def _require_owner(desk: Desk, user: User):
    if desk.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/desks")
async def list_desks(
    sort: str = Query(default="roi_pct"),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    allowed_sorts = {"roi_pct", "net_pnl_usdc", "active_follower_count", "created_at"}
    if sort not in allowed_sorts:
        raise HTTPException(status_code=422, detail="Invalid sort")
    desks = (
        await session.execute(select(Desk).where(Desk.status == "ACTIVE"))
    ).scalars().all()
    records = []
    for d in desks:
        rec = await desk_track_record.compute_track_record(session, d.id)
        records.append((d, rec))
    if sort == "net_pnl_usdc":
        records.sort(key=lambda x: x[1].get("net_pnl_usdc", 0), reverse=True)
    elif sort == "active_follower_count":
        records.sort(key=lambda x: x[1].get("active_follower_count", 0), reverse=True)
    elif sort == "created_at":
        records.sort(key=lambda x: str(x[0].created_at), reverse=True)
    else:
        records.sort(key=lambda x: x[1].get("roi_pct", 0), reverse=True)
    out = []
    for d, rec in records[:limit]:
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "slug": d.slug,
                "description": d.description,
                "active_follower_count": rec.get("active_follower_count", 0),
                "copied_fill_count": rec.get("copied_fill_count", 0),
                "closed_positions": rec.get("closed_positions", 0),
                "win_rate": float(rec.get("win_rate", 0)),
                "roi_pct": float(rec.get("roi_pct", 0)),
                "net_pnl_usdc": float(rec.get("net_pnl_usdc", 0)),
                "max_drawdown_pct": float(rec.get("max_drawdown_pct", 0)),
                "created_at": str(d.created_at),
            }
        )
    return {"desks": out}


@router.post("/desks", status_code=201)
async def create_desk(
    body: CreateDeskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    existing = (
        await session.execute(select(Desk).where(Desk.owner_user_id == user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="DESK_ALREADY_EXISTS")
    desk = Desk(
        owner_user_id=user.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        status="DRAFT",
    )
    session.add(desk)
    await session.flush()
    return {"status": "DRAFT", "desk": _desk_payload(desk)}


@router.get("/desks/mine")
async def get_my_desk(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = (
        await session.execute(select(Desk).where(Desk.owner_user_id == user.id))
    ).scalar_one_or_none()
    if desk is None:
        raise HTTPException(status_code=404, detail="Desk not found")
    record = await desk_track_record.compute_track_record(session, desk.id)
    return {"desk": _desk_payload(desk, record)}


@router.get("/desks/{desk_id}")
async def get_desk(
    desk_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    if desk.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Desk not found")
    record = await desk_track_record.compute_track_record(session, desk.id)
    return {"desk": _desk_payload(desk, record)}


@router.put("/desks/{desk_id}")
async def update_desk(
    desk_id: str,
    body: UpdateDeskRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    if desk.status not in ("DRAFT", "REJECTED"):
        raise HTTPException(status_code=409, detail="DESK_NOT_EDITABLE")
    if body.name is not None:
        desk.name = body.name
    if body.description is not None:
        desk.description = body.description
    await session.flush()
    record = await desk_track_record.compute_track_record(session, desk.id)
    return {"desk": _desk_payload(desk, record)}


@router.post("/desks/{desk_id}/submit")
async def submit_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    if desk.status not in ("DRAFT", "REJECTED", "SUSPENDED"):
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    record = await desk_track_record.compute_track_record(session, desk.id)
    if desk.status in ("DRAFT", "REJECTED"):
        unmet = []
        if record["closed_positions"] < _min_closed_positions():
            unmet.append("closed_positions")
        if record["days_active"] < _min_days_active():
            unmet.append("days_active")
        if unmet:
            raise HTTPException(
                status_code=422,
                detail={"code": "DESK_TRACK_RECORD_INSUFFICIENT", "unmet": unmet},
            )
    desk.status = "PENDING_REVIEW"
    await session.flush()
    return {"status": "PENDING_REVIEW", "desk": _desk_payload(desk, record)}


@router.post("/desks/{desk_id}/suspend")
async def suspend_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    if desk.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    desk.status = "SUSPENDED"
    desk.suspended_at = datetime.now(UTC)
    await session.flush()
    record = await desk_track_record.compute_track_record(session, desk.id)
    return {"status": "SUSPENDED", "desk": _desk_payload(desk, record)}


@router.post("/desks/{desk_id}/archive")
async def archive_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    if desk.status == "ARCHIVED":
        raise HTTPException(status_code=409, detail="DESK_INVALID_TRANSITION")
    desk.status = "ARCHIVED"
    desk.archived_at = datetime.now(UTC)
    followers = (
        await session.execute(select(DeskFollower).where(DeskFollower.desk_id == desk_id))
    ).scalars().all()
    for f in followers:
        f.status = "PAUSED"
        f.updated_at = datetime.now(UTC)
    await session.flush()
    record = await desk_track_record.compute_track_record(session, desk.id)
    return {"status": "ARCHIVED", "desk": _desk_payload(desk, record)}


@router.get("/desks/{desk_id}/track-record")
async def desk_track_record_route(
    desk_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    if desk.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Desk not found")
    record = await desk_track_record.compute_track_record(session, desk.id)
    curve = record.get("curve", [])
    return {"track_record": record, "curve": curve}


@router.get("/desks/{desk_id}/followers")
async def desk_followers(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    followers = (
        await session.execute(select(DeskFollower).where(DeskFollower.desk_id == desk_id))
    ).scalars().all()
    return {
        "followers": [
            {"follower_user_id": f.follower_user_id, "copy_ratio": float(f.copy_ratio), "status": f.status}
            for f in followers
        ]
    }


@router.get("/desks/{desk_id}/copy-jobs")
async def desk_copy_jobs(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    _require_owner(desk, user)
    jobs = (
        await session.execute(
            select(CopyJob).where(CopyJob.desk_id == desk_id).order_by(CopyJob.created_at.desc())
        )
    ).scalars().all()
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    return {
        "counts": counts,
        "jobs": [
            {
                "id": j.id,
                "follower_user_id": j.follower_user_id,
                "status": j.status,
                "copy_ratio": float(j.copy_ratio),
                "requested_shares": float(j.requested_shares),
                "filled_shares": float(j.filled_shares),
                "limit_breached": j.limit_breached,
                "error_code": j.error_code,
                "created_at": str(j.created_at),
            }
            for j in jobs[:50]
        ],
    }


@router.post("/desks/{desk_id}/follow", status_code=201)
async def follow_desk(
    desk_id: str,
    body: FollowRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    desk = await _get_desk(session, desk_id)
    if desk.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="DESK_NOT_ACTIVE")
    if desk.owner_user_id == user.id:
        raise HTTPException(status_code=409, detail="DESK_SELF_FOLLOW")
    existing = (
        await session.execute(
            select(DeskFollower).where(
                DeskFollower.desk_id == desk_id, DeskFollower.follower_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="DESK_ALREADY_FOLLOWED")
    # defaults
    copy_ratio = Decimal(str(body.copy_ratio)) if body.copy_ratio is not None else copy_engine.DEFAULT_COPY_RATIO
    if copy_ratio < copy_engine.MIN_COPY_RATIO or copy_ratio > copy_engine.MAX_COPY_RATIO:
        raise HTTPException(status_code=422, detail="COPY_RATIO_OUT_OF_RANGE")
    per_market_cap = Decimal(str(body.per_market_cap_usdc)) if body.per_market_cap_usdc is not None else copy_engine.DEFAULT_PER_MARKET_CAP
    max_per_market = Decimal(str(body.max_per_market_pct)) if body.max_per_market_pct is not None else copy_engine.MAX_PER_MARKET_PCT
    max_total = Decimal(str(body.max_total_pct)) if body.max_total_pct is not None else copy_engine.MAX_TOTAL_PCT
    if per_market_cap < Decimal("10.0000") or per_market_cap > Decimal("1000000.0000"):
        raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
    if max_per_market < Decimal("1.00") or max_per_market > Decimal("100.00"):
        raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
    if max_total < max_per_market or max_total > Decimal("100.00"):
        raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
    account = await collateral.get_or_create_account(session, user.id)
    available = Decimal(str(account.balance)) - Decimal(str(account.locked_balance))
    if available < Decimal("10.0000"):
        raise HTTPException(status_code=422, detail="INSUFFICIENT_BALANCE")
    follower = DeskFollower(
        desk_id=desk_id,
        follower_user_id=user.id,
        copy_ratio=copy_ratio,
        per_market_cap_usdc=per_market_cap,
        max_per_market_pct=max_per_market,
        max_total_pct=max_total,
        status="ACTIVE",
    )
    session.add(follower)
    await session.flush()
    return {"status": "ACTIVE", "follow": {"copy_ratio": float(copy_ratio)}}


@router.put("/desks/{desk_id}/follow")
async def update_follow(
    desk_id: str,
    body: FollowRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    follower = (
        await session.execute(
            select(DeskFollower).where(
                DeskFollower.desk_id == desk_id, DeskFollower.follower_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if follower is None:
        raise HTTPException(status_code=404, detail="FOLLOW_NOT_FOUND")
    if body.copy_ratio is not None:
        cr = Decimal(str(body.copy_ratio))
        if cr < copy_engine.MIN_COPY_RATIO or cr > copy_engine.MAX_COPY_RATIO:
            raise HTTPException(status_code=422, detail="COPY_RATIO_OUT_OF_RANGE")
        follower.copy_ratio = cr
    if body.per_market_cap_usdc is not None:
        pmc = Decimal(str(body.per_market_cap_usdc))
        if pmc < Decimal("10.0000") or pmc > Decimal("1000000.0000"):
            raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
        follower.per_market_cap_usdc = pmc
    if body.max_per_market_pct is not None:
        mpm = Decimal(str(body.max_per_market_pct))
        if mpm < Decimal("1.00") or mpm > Decimal("100.00"):
            raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
        follower.max_per_market_pct = mpm
    if body.max_total_pct is not None:
        mt = Decimal(str(body.max_total_pct))
        if mt < follower.max_per_market_pct or mt > Decimal("100.00"):
            raise HTTPException(status_code=422, detail="CAP_OUT_OF_RANGE")
        follower.max_total_pct = mt
    if body.status is not None and body.status in ("ACTIVE", "PAUSED"):
        follower.status = body.status
    follower.updated_at = datetime.now(UTC)
    await session.flush()
    return {"status": follower.status}


@router.delete("/desks/{desk_id}/follow", status_code=204)
async def unfollow_desk(
    desk_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    follower = (
        await session.execute(
            select(DeskFollower).where(
                DeskFollower.desk_id == desk_id, DeskFollower.follower_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if follower is None:
        raise HTTPException(status_code=404, detail="FOLLOW_NOT_FOUND")
    await session.delete(follower)
    await session.flush()
    return None


@router.get("/copy-jobs")
async def list_copy_jobs(
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _ensure_enabled()
    stmt = select(CopyJob).where(CopyJob.follower_user_id == user.id)
    if status:
        stmt = stmt.where(CopyJob.status == status)
    jobs = (await session.execute(stmt.order_by(CopyJob.created_at.desc()).limit(limit))).scalars().all()
    return {
        "jobs": [
            {
                "id": j.id,
                "desk_id": j.desk_id,
                "source_fill_id": j.source_fill_id,
                "status": j.status,
                "copy_ratio": float(j.copy_ratio),
                "requested_shares": float(j.requested_shares),
                "filled_shares": float(j.filled_shares),
                "limit_breached": j.limit_breached,
                "error_code": j.error_code,
                "created_at": str(j.created_at),
            }
            for j in jobs
        ]
    }