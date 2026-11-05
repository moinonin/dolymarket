"""Write-behind persistence queue for matched trade fills.

Matching happens against the in-memory book; fills are buffered and inserted
in a single batch at the end of the submission instead of issuing one INSERT
per matched resting order.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.domain import TradeFill


class FillWriteQueue:
    def __init__(self) -> None:
        self._pending: list[TradeFill] = []

    def enqueue(self, fill: TradeFill) -> None:
        self._pending.append(fill)

    def pending(self) -> int:
        return len(self._pending)

    async def flush(self, session: AsyncSession) -> int:
        """Persist every buffered fill in one batched insert.

        Returns the number of rows written. The buffer is always cleared so a
        failed request cannot leak fills into an unrelated session.
        """
        batch, self._pending = self._pending, []
        if not batch:
            return 0
        session.add_all(batch)
        await session.flush()
        return len(batch)

    def discard(self) -> None:
        self._pending.clear()
