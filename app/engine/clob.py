"""Off-chain Central Limit Order Book (CLOB) matching engine.

Implements price-time priority matching, tick integrity validation,
price bounds [0.01, 0.99], time-in-force handling (GTC / IOC / FOK),
post-only maker guarantees, self-trade prevention, collateral locking,
and the parabolic dynamic fee model::

    Fee = C * feeRate * p * (1 - p)
"""
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Event,
    Market,
    Order,
    OutcomeToken,
    Position,
    TradeFill,
)

DEFAULT_FEE_RATE = Decimal("0.02")
CATEGORY_FEE_RATES = {
    "Crypto": Decimal("0.02"),
    "Politics": Decimal("0.015"),
    "Sports": Decimal("0.025"),
    "Macro": Decimal("0.02"),
    "Pop Culture": Decimal("0.02"),
    "Tech": Decimal("0.02"),
}

MIN_PRICE = Decimal("0.01")
MAX_PRICE = Decimal("0.99")


def fee_rate_for_category(category: str | None) -> Decimal:
    return CATEGORY_FEE_RATES.get(category or "", DEFAULT_FEE_RATE)


def compute_fee(shares: Decimal, fee_rate: Decimal, price: Decimal) -> Decimal:
    """Parabolic dynamic fee: C * feeRate * p * (1 - p)."""
    return shares * fee_rate * price * (Decimal(1) - price)


def validate_price(price: Decimal, tick_size: Decimal) -> None:
    if price < MIN_PRICE or price > MAX_PRICE:
        raise ValueError("Price must be between 0.01 and 0.99")
    if tick_size > 0:
        remainder = (price / tick_size).to_integral_value() * tick_size - price
        if abs(remainder) > Decimal("0.0000001"):
            raise ValueError("Price must be a multiple of tick_size")


def to_dec(value: Any) -> Decimal:
    return Decimal(str(value))


class OrderBook:
    """Read-model over persisted orders for a single outcome token."""

    def __init__(self, session: AsyncSession, token_id: str):
        self.session = session
        self.token_id = token_id

    BOOK_STATUSES = ("OPEN", "PARTIALLY_FILLED")

    async def resting_orders(self, side: str) -> list[Order]:
        """Resting orders on ``side`` in price-time priority."""
        stmt = (
            select(Order)
            .where(
                Order.token_id == self.token_id,
                Order.side == side,
                Order.status.in_(self.BOOK_STATUSES),
            )
            .order_by(
                Order.price.desc() if side == "BUY" else Order.price.asc(),
                Order.created_at.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows)

    async def snapshot(self, depth: int = 50) -> dict:
        bids, asks = await self.levels(depth)
        return {
            "token_id": self.token_id,
            "bids": bids,
            "asks": asks,
            "timestamp": int(_now_ns()),
        }

    async def levels(self, depth: int = 50) -> tuple[list, list]:
        async def aggregate(side: str) -> list:
            orders = await self.resting_orders(side)
            acc: dict[str, Decimal] = {}
            for o in orders:
                remaining = to_dec(o.amount) - to_dec(o.filled_amount)
                if remaining > 0:
                    key = str(Decimal(str(o.price)))
                    acc[key] = acc.get(key, Decimal(0)) + remaining
            lvl = [[str(Decimal(k).normalize()), float(v)] for k, v in acc.items()]
            return lvl[:depth]

        bids = await aggregate("BUY")
        asks = await aggregate("SELL")
        return bids, asks

    async def best_bid(self) -> Decimal | None:
        buys = await self.resting_orders("BUY")
        return to_dec(buys[0].price) if buys else None

    async def best_ask(self) -> Decimal | None:
        sells = await self.resting_orders("SELL")
        return to_dec(sells[0].price) if sells else None


def _now_ns() -> int:
    import time

    return time.time_ns() // 1_000_000


class MatchingEngine:
    """Matches incoming aggressive orders against resting DB orders."""

    def __init__(self, broadcaster=None):
        # broadcaster: async callable(events: list[dict]) for WebSocket streaming
        self.broadcaster = broadcaster
        self.last_events: list[dict] = []

    async def _emit(self, events: list[dict]) -> None:
        if self.broadcaster is None:
            return
        await self.broadcaster(events)

    # ------------------------------------------------------------------ submit

    async def submit_order(
        self,
        session: AsyncSession,
        user_id: str,
        market: Market,
        token: OutcomeToken,
        collateral_service,
        side: str,
        price: Decimal | None,
        amount: Decimal,
        order_type: str = "LIMIT",
        time_in_force: str = "GTC",
        post_only: bool = False,
    ) -> Order:
        book = OrderBook(session, token.token_id)
        tick = to_dec(market.tick_size)

        if market.status != "ACTIVE":
            raise OrderRejected(
                f"Market is {market.status}; orders can only be placed while ACTIVE",
                http_status=409,
            )
        if amount <= 0:
            raise OrderRejected("Amount must be positive", http_status=422)
        if to_dec(market.min_order_size) and amount < to_dec(market.min_order_size):
            raise OrderRejected(
                f"Amount below minimum order size ({market.min_order_size})",
                http_status=400,
            )

        if order_type == "MARKET":
            ref = await book.best_ask() if side == "BUY" else await book.best_bid()
            if ref is None:
                raise OrderRejected(
                    "No resting liquidity for market order", http_status=400
                )
            price = ref  # marketable limit at best observable price
        else:
            if price is None:
                raise OrderRejected("Limit orders require a price", http_status=422)
            try:
                validate_price(price, tick)
            except ValueError as exc:
                raise OrderRejected(str(exc), http_status=400)

        order = Order(
            user_id=user_id,
            market_id=market.id,
            token_id=token.token_id,
            side=side,
            type=order_type,
            price=price,
            amount=amount,
            filled_amount=0,
            status="OPEN",
            time_in_force=time_in_force,
            post_only=post_only,
        )
        session.add(order)
        await session.flush()

        events: list[dict] = []

        post_only_cross = await self._would_cross(book, side, price)
        if post_only and post_only_cross:
            order.status = "REJECTED"
            raise OrderRejected(
                "post-only order would cross the spread", http_status=409
            )

        # Self-trade prevention: reject if the top-of-book order is ours.
        opposite = "SELL" if side == "BUY" else "BUY"
        resting = await book.resting_orders(opposite)
        relevant = [
            o
            for o in resting
            if (to_dec(o.price) <= price if side == "BUY" else to_dec(o.price) >= price)
        ]
        if relevant and relevant[0].user_id == user_id:
            order.status = "REJECTED"
            self.last_events = events
            return order

        # Collateral / share locking.
        if side == "BUY":
            cost = price * amount
            await collateral_service.lock_for_buy(session, user_id, cost)
        else:
            position = await self._get_position(session, user_id, token.token_id)
            if position is None or to_dec(position.shares) - to_dec(
                position.locked_shares
            ) < amount:
                raise OrderRejected(
                    "Insufficient outcome token shares for SELL", http_status=400
                )
            position.locked_shares = to_dec(position.locked_shares) + amount
            events.append(
                {
                    "channel": "pred.positions",
                    "user_id": user_id,
                    "token_id": token.token_id,
                    "shares": float(position.shares),
                    "locked_shares": float(position.locked_shares),
                }
            )

        if time_in_force == "FOK":
            liquidity = sum(
                min(to_dec(o.amount) - to_dec(o.filled_amount), amount)
                for o in relevant
            )
            if liquidity < amount:
                order.status = "REJECTED"
                await self._release_all(session, order, collateral_service)
                self.last_events = events
                return order

        # Match against resting liquidity (price-time priority).
        remaining = amount
        for maker in relevant[:]:
            if remaining <= 0:
                break
            fill_price = to_dec(maker.price)
            maker_remaining = to_dec(maker.amount) - to_dec(maker.filled_amount)
            qty = min(maker_remaining, remaining)
            if qty <= 0:
                continue
            fill = await self._execute_fill(
                session,
                market,
                token,
                maker,
                order,
                fill_price,
                qty,
                collateral_service,
            )
            events.append(
                {
                    "channel": "pred.trades",
                    "market_id": market.id,
                    "token_id": token.token_id,
                    "price": float(fill_price),
                    "shares": float(qty),
                    "side": side,
                    "timestamp": _now_ns(),
                }
            )
            events.extend(fill.pop("position_events", []))
            remaining -= qty

        order.filled_amount = amount - remaining

        if remaining > 0:
            if time_in_force == "GTC" and order_type == "LIMIT":
                order.status = (
                    "PARTIALLY_FILLED" if order.filled_amount > 0 else "OPEN"
                )
            else:  # IOC remainder (FOK remainder handled above)
                order.status = "CANCELLED"
                await self._release_all(session, order, collateral_service)
        else:
            order.status = "FILLED"
            await self._emit(events)
            self.last_events = events
            return order

        events.append(
            {
                "channel": "pred.orders",
                "user_id": user_id,
                "order_id": order.id,
                "status": order.status,
                "filled_amount": float(order.filled_amount),
                "remaining_amount": float(remaining),
            }
        )
        await self._emit(events)
        self.last_events = events
        return order

    async def _would_cross(
        self, book: OrderBook, side: str, price: Decimal
    ) -> bool:
        if side == "BUY":
            best_ask = await book.best_ask()
            return best_ask is not None and price >= best_ask
        best_bid = await book.best_bid()
        return best_bid is not None and price <= best_bid

    async def _execute_fill(
        self,
        session: AsyncSession,
        market: Market,
        token: OutcomeToken,
        maker: Order,
        taker: Order,
        fill_price: Decimal,
        qty: Decimal,
        collateral_service,
    ) -> dict:
        category = None
        event = (
            await session.execute(select(Event).where(Event.id == market.event_id))
        ).scalar_one_or_none()
        if event is not None:
            category = event.category
        fee_rate = fee_rate_for_category(category)
        maker_fee = compute_fee(qty, fee_rate, fill_price)
        taker_fee = compute_fee(qty, fee_rate, fill_price)

        fill = TradeFill(
            market_id=market.id,
            token_id=token.token_id,
            maker_order_id=maker.id,
            taker_order_id=taker.id,
            maker_user_id=maker.user_id,
            taker_user_id=taker.user_id,
            price=fill_price,
            shares=qty,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
        )
        session.add(fill)

        maker.filled_amount = to_dec(maker.filled_amount) + qty
        maker_remaining = to_dec(maker.amount) - to_dec(maker.filled_amount)
        maker.status = "FILLED" if maker_remaining <= 0 else "PARTIALLY_FILLED"

        taker.filled_amount = to_dec(taker.filled_amount) + qty

        # --- settlement of funds -------------------------------------------
        taker_account = await collateral_service.resolve_account(
            session, taker.user_id
        )
        maker_account = await collateral_service.resolve_account(
            session, maker.user_id
        )

        if taker.side == "BUY":
            # Release lock for consumed shares and pay the maker notional.
            await collateral_service.release_lock(
                session, taker_account, fill_price * qty
            )
            notional = fill_price * qty
            taker_account.balance = to_dec(taker_account.balance) - notional
            maker_account.balance = to_dec(maker_account.balance) + notional
            collateral_service.charge_fee_sync(taker_account, taker_fee)
            collateral_service.charge_fee_sync(maker_account, maker_fee)
        else:
            # Taker sells shares; maker buys.
            await collateral_service.release_lock(
                session, maker_account, fill_price * qty
            )
            notional = fill_price * qty
            maker_account.balance = to_dec(maker_account.balance) - notional
            taker_account.balance = to_dec(taker_account.balance) + notional
            collateral_service.charge_fee_sync(taker_account, taker_fee)
            collateral_service.charge_fee_sync(maker_account, maker_fee)

        position_events = []
        for user_id, role, order in (
            (maker.user_id, "maker", maker),
            (taker.user_id, "taker", taker),
        ):
            position = await self._get_position(session, user_id, token.token_id)
            if position is None:
                position = Position(
                    user_id=user_id,
                    market_id=market.id,
                    token_id=token.token_id,
                    shares=0,
                    locked_shares=0,
                )
                session.add(position)
                await session.flush()
            delta = qty if order.side == "BUY" else -qty
            new_shares = to_dec(position.shares) + delta
            if delta > 0:
                old_shares = to_dec(position.shares)
                old_avg = to_dec(position.avg_entry_price)
                total = old_shares + qty
                position.avg_entry_price = (
                    (old_shares * old_avg + qty * fill_price) / total
                    if total > 0
                    else fill_price
                )
            else:
                avg = to_dec(position.avg_entry_price)
                realized = (fill_price - avg) * (-delta)
                position.realized_pnl = to_dec(position.realized_pnl) + realized
            if order.side == "SELL":
                # Both maker-side and taker-side sells release locked shares.
                position.locked_shares = max(
                    Decimal(0), to_dec(position.locked_shares) - qty
                )
            position.shares = max(Decimal(0), new_shares)
            position_events.append(
                {
                    "channel": "pred.positions",
                    "user_id": user_id,
                    "token_id": token.token_id,
                    "shares": float(position.shares),
                    "avg_entry_price": float(position.avg_entry_price),
                    "role": role,
                }
            )

        position_events.append(
            {
                "channel": "pred.usertrades",
                "maker_user_id": maker.user_id,
                "taker_user_id": taker.user_id,
                "fill_id": fill.id,
                "order_id": taker.id,
                "price": float(fill_price),
                "shares": float(qty),
                "fee_paid": float(taker_fee),
                "role": "taker",
            }
        )
        return {"position_events": position_events}

    async def _release_all(self, session: AsyncSession, order: Order, collateral_service) -> None:
        remaining = to_dec(order.amount) - to_dec(order.filled_amount)
        price = to_dec(order.price)
        if order.side == "BUY":
            account = await collateral_service.resolve_account(session, order.user_id)
            await collateral_service.release_lock(session, account, price * remaining)
        else:
            position = await self._get_position(session, order.user_id, order.token_id)
            if position is not None:
                position.locked_shares = max(
                    Decimal(0), to_dec(position.locked_shares) - remaining
                )

    async def cancel_order(
        self, session: AsyncSession, order: Order, collateral_service
    ) -> dict:
        remaining = to_dec(order.amount) - to_dec(order.filled_amount)
        order.status = "CANCELLED"
        await self._release_all(session, order, collateral_service)
        return {
            "order_id": order.id,
            "status": "CANCELLED",
            "unfilled_amount": float(remaining),
        }

    async def _get_position(
        self, session: AsyncSession, user_id: str, token_id: str
    ) -> Position | None:
        return (
            await session.execute(
                select(Position).where(
                    Position.user_id == user_id, Position.token_id == token_id
                )
            )
        ).scalar_one_or_none()


class OrderRejected(Exception):
    def __init__(self, detail: str, http_status: int = 400, rejected: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.http_status = http_status
        self.rejected = rejected
