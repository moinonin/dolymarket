"""Authoritative partition leases, durable sequences, and transactional outbox."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import OutboxEvent, TokenPartitionState


def _now() -> datetime:
    return datetime.now(UTC)


async def _get_or_create_partition(
    session: AsyncSession, token_id: str, *, for_update: bool = True
) -> TokenPartitionState:
    stmt = select(TokenPartitionState).where(TokenPartitionState.token_id == token_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = TokenPartitionState(token_id=token_id, last_sequence_id=0)
        if hasattr(session, "begin_nested"):
            try:
                async with session.begin_nested():
                    session.add(row)
                    await session.flush()
            except IntegrityError:
                row = (await session.execute(stmt)).scalar_one()
        else:
            session.add(row)
            await session.flush()
    return row


async def claim_partition_lease(
    session: AsyncSession,
    token_id: str,
    leader_id: str,
    ttl_seconds: int = 30,
) -> bool:
    """Attempt to acquire or renew the authoritative leader lease for ``token_id``."""
    row = await _get_or_create_partition(session, token_id, for_update=True)
    now = _now()
    exp = row.lease_expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if row.leader_id is None or row.leader_id == leader_id or exp is None or exp <= now:
        row.leader_id = leader_id
        row.lease_expires_at = now + timedelta(seconds=ttl_seconds)
        row.updated_at = now
        await session.flush()
        return True
    return False


async def allocate_partition_sequences(
    session: AsyncSession, token_id: str, count: int = 1
) -> list[int]:
    """Atomically allocate ``count`` durable monotonic sequence IDs for ``token_id``."""
    if count <= 0:
        return []
    row = await _get_or_create_partition(session, token_id, for_update=True)
    start = int(row.last_sequence_id or 0) + 1
    row.last_sequence_id = start + count - 1
    row.updated_at = _now()
    await session.flush()
    return list(range(start, start + count))


async def enqueue_outbox_events(
    session: AsyncSession, token_id: str | None, events: list[dict[str, Any]]
) -> list[OutboxEvent]:
    """Persist engine events into the transactional outbox within the active DB transaction."""
    if not events:
        return []
    rows: list[OutboxEvent] = []
    for ev in events:
        seq = int(ev.get("partition_seq") or ev.get("sequence_id") or 0)
        row = OutboxEvent(
            token_id=token_id,
            partition_seq=seq,
            channel=str(ev.get("channel") or "unknown"),
            payload_json=dict(ev),
            published=False,
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    return rows


async def relay_pending_outbox(
    session: AsyncSession, broadcaster: Any, limit: int = 100
) -> int:
    """Relay unpublished committed outbox events to ``broadcaster`` and mark published."""
    rows = (
        await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published.is_(False))
            .order_by(OutboxEvent.created_at.asc(), OutboxEvent.partition_seq.asc())
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        return 0
    payloads = [dict(r.payload_json) for r in rows]
    if broadcaster is not None:
        await broadcaster(payloads)
    now = _now()
    for r in rows:
        r.published = True
        r.published_at = now
    await session.flush()
    return len(rows)
