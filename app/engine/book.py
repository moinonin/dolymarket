"""In-memory price-time-priority order books.

The matching engine keeps a live book per outcome token in process memory.
Orders are hydrated from the database once per token, then all resting-order
lookups and matching decisions run against the in-memory structure. Only the
small set of orders that actually match is re-loaded through the ORM for
settlement, which removes the full-table scan from the hot path.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sequencer import sequencer

BOOK_STATUSES = ("OPEN", "PARTIALLY_FILLED")


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


@dataclass
class BookOrder:
    """Scalar snapshot of a resting order (detached from any SQLAlchemy session)."""

    id: str
    user_id: str
    side: str
    price: Decimal
    amount: Decimal
    filled_amount: Decimal
    status: str
    created_at: datetime | None = None
    sequence: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.filled_amount

    @classmethod
    def from_orm(cls, order) -> "BookOrder":
        return cls(
            id=order.id,
            user_id=order.user_id,
            side=order.side,
            price=_dec(order.price),
            amount=_dec(order.amount),
            filled_amount=_dec(order.filled_amount),
            status=order.status,
            created_at=getattr(order, "created_at", None),
            sequence=getattr(order, "sequence_id", 0) or 0,
        )


class InMemoryOrderBook:
    """Dual-sided book: bids descending, asks ascending, FIFO per price level."""

    def __init__(self, token_id: str) -> None:
        self.token_id = token_id
        self.bids: dict[Decimal, list[BookOrder]] = defaultdict(list)
        self.asks: dict[Decimal, list[BookOrder]] = defaultdict(list)
        self.last_sequence = 0
        self._loaded = False
        self._load_lock = asyncio.Lock()

    # ------------------------------------------------------------------ load
    async def ensure_loaded(self, session: AsyncSession) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            rows = (
                await session.execute(
                    select(_order_model()).where(
                        _order_model().token_id == self.token_id,
                        _order_model().status.in_(BOOK_STATUSES),
                    )
                )
            ).scalars().all()
            for row in rows:
                self._insert(BookOrder.from_orm(row))
            self._loaded = True

    # --------------------------------------------------------------- mutation
    def _side(self, side: str) -> dict[Decimal, list[BookOrder]]:
        return self.bids if side == "BUY" else self.asks

    def _insert(self, record: BookOrder) -> None:
        if record.remaining <= 0 or record.status not in BOOK_STATUSES:
            return
        level = self._side(record.side)[record.price]
        for idx, existing in enumerate(level):
            if existing.id == record.id:
                level[idx] = record
                return
        level.append(record)
        level.sort(key=lambda o: _time_key(o.created_at))

    def add_order(self, order) -> BookOrder:
        record = BookOrder.from_orm(order)
        record.sequence = sequencer.next()
        self.last_sequence = record.sequence
        self._insert(record)
        return record

    def update_order(self, order) -> None:
        record = BookOrder.from_orm(order)
        self.remove_order(record.id)
        if record.remaining > 0 and record.status in BOOK_STATUSES:
            record.sequence = sequencer.next()
            self.last_sequence = record.sequence
            self._insert(record)

    def invalidate(self) -> None:
        """Drop the cached state so the book is re-hydrated from persistence.

        Used when a transaction rolls back after the book was already
        mutated: the next access rebuilds the book from the committed rows
        instead of serving stale in-memory liquidity.
        """
        self.bids.clear()
        self.asks.clear()
        self.last_sequence = 0
        self._loaded = False

    def remove_order(self, order_id: str) -> None:
        for side in (self.bids, self.asks):
            for price in list(side):
                level = side[price]
                filtered = [o for o in level if o.id != order_id]
                if len(filtered) != len(level):
                    if filtered:
                        side[price] = filtered
                    else:
                        del side[price]
                    return

    def next_sequence(self) -> int:
        self.last_sequence = sequencer.next()
        return self.last_sequence

    # ----------------------------------------------------------------- reads
    def resting_orders(self, side: str, limit: int | None = None) -> list[BookOrder]:
        prices = sorted(self.bids, reverse=True) if side == "BUY" else sorted(self.asks)
        out: list[BookOrder] = []
        for price in prices:
            out.extend(self._side(side)[price])
            if limit is not None and len(out) >= limit:
                return out[:limit]
        return out

    def best_bid(self) -> Decimal | None:
        prices = [p for p in self.bids if self.bids[p]]
        return max(prices) if prices else None

    def best_ask(self) -> Decimal | None:
        prices = [p for p in self.asks if self.asks[p]]
        return min(prices) if prices else None

    def levels(self, depth: int = 50) -> tuple[list, list]:
        def aggregate(book: dict[Decimal, list[BookOrder]], reverse: bool) -> list:
            out = []
            for price in sorted(book, reverse=reverse):
                size = sum((o.remaining for o in book[price]), Decimal(0))
                if size > 0:
                    out.append([str(price.normalize()), float(size)])
                if len(out) >= depth:
                    break
            return out

        return aggregate(self.bids, True), aggregate(self.asks, False)

    def snapshot(self, depth: int = 50) -> dict:
        bids, asks = self.levels(depth)
        seq = max(self.last_sequence, sequencer.current())
        from app.ws.sequence import stream_sequencer

        return {
            "token_id": self.token_id,
            "bids": bids,
            "asks": asks,
            "sequence": seq,
            "stream_sequence": stream_sequencer.current(),
            "timestamp": int(_now_ms()),
        }


class OrderBookRegistry:
    """Process-wide registry of live books, hydrated lazily from persistence."""

    def __init__(self) -> None:
        self._books: dict[str, InMemoryOrderBook] = {}

    def get_existing(self, token_id: str) -> InMemoryOrderBook | None:
        return self._books.get(token_id)

    async def get(self, session: AsyncSession, token_id: str) -> InMemoryOrderBook:
        book = self._books.get(token_id)
        if book is None:
            book = InMemoryOrderBook(token_id)
            self._books[token_id] = book
        await book.ensure_loaded(session)
        return book

    def invalidate(self, token_id: str) -> None:
        """Forget a book's cached state (transaction rolled back)."""
        book = self._books.pop(token_id, None)
        if book is not None:
            book.invalidate()

    def reset(self) -> None:
        self._books.clear()


order_books = OrderBookRegistry()


def reset_sequence_state() -> None:
    sequencer.reset()
    order_books.reset()


def _time_key(value: datetime | None) -> float:
    if value is None:
        return 0.0
    try:
        return value.timestamp()
    except (OSError, ValueError):  # pragma: no cover - defensive
        return 0.0


def _now_ms() -> int:
    import time

    return time.time_ns() // 1_000_000


def _order_model():
    from app.models.domain import Order

    return Order
