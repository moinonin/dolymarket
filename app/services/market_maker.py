"""Fear & Greed Market-Making Pro Desk strategy engine.

Consumes live readings from ``fear_greed_service`` (microstructure, 10s) and
computes inventory-skewed, EWI-regime-gated two-sided ``post_only`` quotes.
Supports dry-run paper quoting and live local CLOB execution (Phase A).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.engine.clob import MatchingEngine, OrderBook, OrderRejected
from app.models.domain import (
    DeskMarketMakerConfig,
    DeskPosition,
    Event,
    Market,
    Order,
    OutcomeToken,
    TradeFill,
)
from app.services import collateral
from app.services.fear_greed import fear_greed_service
from app.ws.broadcaster import broadcast_engine_events

logger = logging.getLogger(__name__)

MIN_PX = Decimal("0.01")
MAX_PX = Decimal("0.99")


def _quantize_tick(price: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        tick = Decimal("0.01")
    steps = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    q = steps * tick
    return max(MIN_PX, min(MAX_PX, q))


@dataclass
class MMConfig:
    desk_id: str
    market_id: str
    token_id: str
    owner_user_id: str
    base_half_spread: Decimal = Decimal("0.02")
    quote_size: Decimal = Decimal("10")
    max_inventory: Decimal = Decimal("100")
    max_usdc_exposure: Decimal = Decimal("500")
    desk_max_total_exposure_usdc: Decimal = Decimal("2000")
    daily_loss_limit_usdc: Decimal = Decimal("50")
    expiry_pull_minutes: int = 15
    local_jump_halt: Decimal = Decimal("0.08")
    tick_size: Decimal = Decimal("0.01")
    k_fg: float = 0.04
    k_vel: float = 0.25
    gamma: float = 0.03
    ewi_elevated: float = 0.45
    ewi_critical: float = 0.75
    ewi_resume: float = 0.55
    crypto_skew: bool = True
    dry_run: bool = True
    interval_s: float = 2.0


@dataclass
class QuoteDecision:
    action: str  # "QUOTE" | "HALT"
    reason: str
    regime_state: str
    ewi: float
    score_0_100: float
    fair_value: Decimal
    bid_price: Decimal | None
    ask_price: Decimal | None
    quote_size: Decimal
    halted: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fair_value"] = str(self.fair_value)
        d["bid_price"] = str(self.bid_price) if self.bid_price is not None else None
        d["ask_price"] = str(self.ask_price) if self.ask_price is not None else None
        d["quote_size"] = str(self.quote_size)
        return d


def compute_quotes(
    *,
    book_mid: Decimal,
    inventory: Decimal,
    reading: dict[str, Any],
    cfg: MMConfig,
    was_halted: bool = False,
    prev_book_mid: Decimal | None = None,
    seconds_to_expiry: float | None = None,
    realized_loss_usdc: Decimal = Decimal("0"),
    desk_exposure_usdc: Decimal = Decimal("0"),
) -> QuoteDecision:
    """Pure quoting function: Fear & Greed + inventory skew + EWI/expiry/capital circuit breakers."""
    ewi = float(reading.get("ewi", 0.0))
    score = float(reading.get("score_0_100", 50.0))
    v_alpha = float(reading.get("v_alpha", 0.0))
    regime = str(reading.get("regime_state", "STABLE"))
    early_warning = bool(reading.get("early_warning", False))

    # 0. Reference feed freshness, pre-expiry, daily loss, and local midpoint-jump toxicity guards
    age_s = reading.get("age_seconds")
    if age_s is not None and float(age_s) > 120.0:
        return QuoteDecision(
            action="HALT",
            reason="STALE_REFERENCE_FEED",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )
    if cfg.daily_loss_limit_usdc > 0 and realized_loss_usdc >= cfg.daily_loss_limit_usdc:
        return QuoteDecision(
            action="HALT",
            reason="DAILY_LOSS_LIMIT",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )
    if (
        cfg.desk_max_total_exposure_usdc > 0
        and desk_exposure_usdc >= cfg.desk_max_total_exposure_usdc
        and inventory == 0
    ):
        return QuoteDecision(
            action="HALT",
            reason="DESK_TOTAL_EXPOSURE_CAP",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )
    if seconds_to_expiry is not None and seconds_to_expiry <= cfg.expiry_pull_minutes * 60:
        return QuoteDecision(
            action="HALT",
            reason="PRE_EXPIRY_PULL",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )
    if prev_book_mid is not None and abs(book_mid - prev_book_mid) >= cfg.local_jump_halt:
        return QuoteDecision(
            action="HALT",
            reason="LOCAL_TOXICITY_JUMP",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )

    # 1. Toxicity / regime-flip circuit breaker with hysteresis
    if ewi >= cfg.ewi_critical or early_warning or regime == "CRITICAL":
        return QuoteDecision(
            action="HALT",
            reason="CRITICAL_EWI",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )
    if was_halted and ewi >= cfg.ewi_resume:
        return QuoteDecision(
            action="HALT",
            reason="HYSTERESIS_WAIT",
            regime_state=regime,
            ewi=ewi,
            score_0_100=score,
            fair_value=book_mid,
            bid_price=None,
            ask_price=None,
            quote_size=Decimal("0"),
            halted=True,
        )

    # 2. Regime-gated spread & size multipliers
    if ewi >= cfg.ewi_elevated or regime == "ELEVATED":
        spread_mult = Decimal("2.5")
        size_mult = Decimal("0.5")
    else:
        spread_mult = Decimal("1")
        size_mult = Decimal("1")

    # 3. Sentiment + velocity + inventory skew
    fg_skew = 0.0
    if cfg.crypto_skew:
        fg_skew = cfg.k_fg * ((score - 50.0) / 50.0) + cfg.k_vel * v_alpha

    inv_ratio = 0.0
    if cfg.max_inventory > 0:
        inv_ratio = max(-1.0, min(1.0, float(inventory / cfg.max_inventory)))
    inv_skew = -cfg.gamma * inv_ratio

    raw_fair = book_mid + Decimal(str(round(fg_skew + inv_skew, 6)))
    fair = max(Decimal("0.02"), min(Decimal("0.98"), raw_fair)).quantize(Decimal("0.0001"))

    half_spread = cfg.base_half_spread * spread_mult
    bid_px: Decimal | None = _quantize_tick(fair - half_spread, cfg.tick_size)
    ask_px: Decimal | None = _quantize_tick(fair + half_spread, cfg.tick_size)

    if bid_px >= ask_px:
        bid_px = max(MIN_PX, _quantize_tick(fair - cfg.tick_size, cfg.tick_size))
        ask_px = min(MAX_PX, _quantize_tick(fair + cfg.tick_size, cfg.tick_size))

    # Enforce hard inventory & USDC exposure caps
    if inventory >= cfg.max_inventory:
        bid_px = None
    if inventory <= -cfg.max_inventory:
        ask_px = None

    size = (cfg.quote_size * size_mult).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    if cfg.max_usdc_exposure > 0 and fair > 0:
        used_usdc = abs(inventory) * fair
        remaining_usdc = cfg.max_usdc_exposure - used_usdc
        if remaining_usdc <= 0:
            if inventory >= 0:
                bid_px = None
            if inventory <= 0:
                ask_px = None
        else:
            max_shares = (remaining_usdc / fair).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            size = min(size, max_shares)
    return QuoteDecision(
        action="QUOTE",
        reason="OK",
        regime_state=regime,
        ewi=ewi,
        score_0_100=score,
        fair_value=fair,
        bid_price=bid_px,
        ask_price=ask_px,
        quote_size=size,
        halted=False,
    )


@dataclass
class MMRuntimeState:
    cfg: MMConfig
    running: bool = False
    halted: bool = False
    ticks: int = 0
    orders_placed: int = 0
    orders_cancelled: int = 0
    last_error: str | None = None
    last_decision: dict[str, Any] | None = None
    last_tick_at: float | None = None
    resting_bid_id: str | None = None
    resting_bid_px: Decimal | None = None
    resting_ask_id: str | None = None
    resting_ask_px: Decimal | None = None
    prev_book_mid: Decimal | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "desk_id": self.cfg.desk_id,
            "market_id": self.cfg.market_id,
            "token_id": self.cfg.token_id,
            "dry_run": self.cfg.dry_run,
            "crypto_skew": self.cfg.crypto_skew,
            "max_usdc_exposure": str(self.cfg.max_usdc_exposure),
            "daily_loss_limit_usdc": str(self.cfg.daily_loss_limit_usdc),
            "expiry_pull_minutes": self.cfg.expiry_pull_minutes,
            "running": self.running,
            "halted": self.halted,
            "ticks": self.ticks,
            "orders_placed": self.orders_placed,
            "orders_cancelled": self.orders_cancelled,
            "last_error": self.last_error,
            "last_decision": self.last_decision,
            "last_tick_at": self.last_tick_at,
        }


class FearGreedMarketMakerManager:
    """Manages active market-making loops per (Desk, Token) with distributed lease fencing."""

    def __init__(self) -> None:
        import uuid

        self._desks: dict[str, MMRuntimeState] = {}
        self.instance_id: str = f"mm-{uuid.uuid4().hex[:8]}"
        self.global_kill_switch: bool = False

    async def kill_all(self) -> int:
        """Global kill switch: halt & stop every active MM bot and cancel resting quotes."""
        self.global_kill_switch = True
        stopped = 0
        for st in list(self._desks.values()):
            await self._stop_state(st)
            stopped += 1
        return stopped

    @staticmethod
    def _key(desk_id: str, token_id: str) -> str:
        return f"{desk_id}:{token_id}"

    def _desk_bots(self, desk_id: str) -> list[MMRuntimeState]:
        prefix = f"{desk_id}:"
        return [st for k, st in self._desks.items() if k.startswith(prefix)]

    def get_status(self, desk_id: str, token_id: str | None = None) -> dict[str, Any] | None:
        if token_id:
            st = self._desks.get(self._key(desk_id, token_id))
            return st.to_status_dict() if st else None
        bots = self._desk_bots(desk_id)
        if not bots:
            return None
        primary = next((b for b in bots if b.running), bots[-1]).to_status_dict()
        primary["bots"] = [b.to_status_dict() for b in bots]
        return primary

    async def _persist_config(self, cfg: MMConfig, *, enabled: bool) -> None:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(DeskMarketMakerConfig).where(
                        DeskMarketMakerConfig.desk_id == cfg.desk_id,
                        DeskMarketMakerConfig.token_id == cfg.token_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = DeskMarketMakerConfig(
                    desk_id=cfg.desk_id,
                    token_id=cfg.token_id,
                    owner_user_id=cfg.owner_user_id,
                )
                session.add(row)
            row.owner_user_id = cfg.owner_user_id
            row.market_id = cfg.market_id
            row.base_half_spread = cfg.base_half_spread
            row.quote_size = cfg.quote_size
            row.max_inventory = cfg.max_inventory
            row.max_usdc_exposure = cfg.max_usdc_exposure
            row.daily_loss_limit_usdc = cfg.daily_loss_limit_usdc
            row.expiry_pull_minutes = cfg.expiry_pull_minutes
            row.tick_size = cfg.tick_size
            row.crypto_skew = cfg.crypto_skew
            row.dry_run = cfg.dry_run
            row.interval_s = Decimal(str(cfg.interval_s))
            row.enabled = enabled
            await session.commit()

    async def _set_disabled(self, desk_id: str, token_id: str | None = None) -> None:
        async with AsyncSessionLocal() as session:
            stmt = select(DeskMarketMakerConfig).where(DeskMarketMakerConfig.desk_id == desk_id)
            if token_id:
                stmt = stmt.where(DeskMarketMakerConfig.token_id == token_id)
            rows = (await session.execute(stmt)).scalars().all()
            changed = False
            for row in rows:
                if row.enabled:
                    row.enabled = False
                    changed = True
            if changed:
                await session.commit()

    async def start(self, cfg: MMConfig, *, persist: bool = True) -> dict[str, Any]:
        await self.stop(cfg.desk_id, token_id=cfg.token_id, persist=False)
        if persist:
            await self._persist_config(cfg, enabled=True)
        state = MMRuntimeState(cfg=cfg, running=True)
        self._desks[self._key(cfg.desk_id, cfg.token_id)] = state
        # Run an immediate tick so status has an initial decision right away
        await self._step(state)
        state.task = asyncio.create_task(self._loop(state))
        res = state.to_status_dict()
        res["bots"] = [b.to_status_dict() for b in self._desk_bots(cfg.desk_id)]
        return res

    async def _stop_state(self, state: MMRuntimeState) -> dict[str, Any]:
        state.running = False
        if state.task and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
        if not state.cfg.dry_run:
            await self._cancel_resting(state)
        return state.to_status_dict()

    async def stop(
        self, desk_id: str, token_id: str | None = None, *, persist: bool = True
    ) -> dict[str, Any] | None:
        if persist:
            await self._set_disabled(desk_id, token_id=token_id)
        if token_id:
            state = self._desks.get(self._key(desk_id, token_id))
            return await self._stop_state(state) if state else None
        bots = self._desk_bots(desk_id)
        if not bots:
            return None
        last_status = None
        for b in bots:
            last_status = await self._stop_state(b)
        return last_status

    async def resume_enabled(self) -> int:
        """Auto-resume all DB-persisted enabled market makers on startup."""
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(DeskMarketMakerConfig).where(DeskMarketMakerConfig.enabled.is_(True))
                )
            ).scalars().all()
        resumed = 0
        for row in rows:
            cfg = MMConfig(
                desk_id=row.desk_id,
                market_id=row.market_id,
                token_id=row.token_id,
                owner_user_id=row.owner_user_id,
                base_half_spread=Decimal(str(row.base_half_spread)),
                quote_size=Decimal(str(row.quote_size)),
                max_inventory=Decimal(str(row.max_inventory)),
                max_usdc_exposure=Decimal(str(getattr(row, "max_usdc_exposure", "500"))),
                daily_loss_limit_usdc=Decimal(str(getattr(row, "daily_loss_limit_usdc", "50"))),
                expiry_pull_minutes=int(getattr(row, "expiry_pull_minutes", 15)),
                tick_size=Decimal(str(row.tick_size)),
                crypto_skew=bool(row.crypto_skew),
                dry_run=bool(row.dry_run),
                interval_s=float(row.interval_s),
            )
            await self.start(cfg, persist=False)
            resumed += 1
        if resumed:
            logger.info("Resumed %d persisted desk market maker(s)", resumed)
        return resumed

    async def stop_all(self) -> None:
        """Stop all running loops on shutdown without disabling DB persistence."""
        for st in list(self._desks.values()):
            await self._stop_state(st)

    async def _loop(self, state: MMRuntimeState) -> None:
        while state.running:
            await asyncio.sleep(max(0.5, state.cfg.interval_s))
            if not state.running:
                break
            await self._step(state)

    async def _cancel_resting(self, state: MMRuntimeState) -> None:
        ids = [oid for oid in (state.resting_bid_id, state.resting_ask_id) if oid]
        if not ids:
            return
        async with AsyncSessionLocal() as session:
            engine = MatchingEngine(broadcaster=broadcast_engine_events)
            for oid in ids:
                order = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
                if order and order.status in ("OPEN", "PARTIALLY_FILLED"):
                    await engine.cancel_order(session, order, collateral)
                    state.orders_cancelled += 1
            await session.commit()
        state.resting_bid_id = None
        state.resting_bid_px = None
        state.resting_ask_id = None
        state.resting_ask_px = None

    async def _step(self, state: MMRuntimeState) -> None:
        import os

        if self.global_kill_switch or os.environ.get("MM_GLOBAL_KILL_SWITCH", "").strip() == "1":
            await self._cancel_resting(state)
            state.halted = True
            return
        cfg = state.cfg
        try:
            reading = await fear_greed_service.get_latest("microstructure")
            book_mid = Decimal("0.50")
            inventory = Decimal("0")

            async with AsyncSessionLocal() as session:
                from app.services import outbox

                has_lease = await outbox.claim_partition_lease(
                    session,
                    f"mm:{cfg.desk_id}:{cfg.token_id}",
                    self.instance_id,
                    ttl_seconds=30,
                )
                if not has_lease:
                    state.last_error = "STANDBY_NO_LEASE"
                    return
                book = OrderBook(session, cfg.token_id)
                best_bid = await book.best_bid()
                best_ask = await book.best_ask()
                if best_bid is not None and best_ask is not None:
                    book_mid = (best_bid + best_ask) / Decimal("2")
                elif best_bid is not None:
                    book_mid = best_bid
                elif best_ask is not None:
                    book_mid = best_ask
                else:
                    last_fill = (
                        await session.execute(
                            select(TradeFill.price)
                            .where(TradeFill.token_id == cfg.token_id)
                            .order_by(TradeFill.sequence_id.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if last_fill is not None:
                        book_mid = Decimal(str(last_fill))

                pos = (
                    await session.execute(
                        select(DeskPosition).where(
                            DeskPosition.desk_id == cfg.desk_id,
                            DeskPosition.market_id == cfg.market_id,
                            DeskPosition.token_id == cfg.token_id,
                        )
                    )
                ).scalar_one_or_none()
                realized_loss = Decimal("0")
                if pos and pos.size is not None:
                    inventory = Decimal(str(pos.size))
                if pos and pos.realized_pnl is not None and Decimal(str(pos.realized_pnl)) < 0:
                    realized_loss = abs(Decimal(str(pos.realized_pnl)))

                all_desk_positions = (
                    await session.execute(
                        select(DeskPosition).where(DeskPosition.desk_id == cfg.desk_id)
                    )
                ).scalars().all()
                desk_exposure_usdc = sum(
                    abs(Decimal(str(p.size or 0))) * Decimal(str(p.avg_entry or book_mid))
                    for p in all_desk_positions
                )

                market = (
                    await session.execute(select(Market).where(Market.id == cfg.market_id))
                ).scalar_one_or_none()
                seconds_to_expiry: float | None = None
                if market and market.event_id:
                    ev = (
                        await session.execute(select(Event).where(Event.id == market.event_id))
                    ).scalar_one_or_none()
                    if ev and ev.end_date is not None:
                        end_dt = ev.end_date if ev.end_date.tzinfo else ev.end_date.replace(tzinfo=UTC)
                        seconds_to_expiry = (end_dt - datetime.now(UTC)).total_seconds()

                decision = compute_quotes(
                    book_mid=book_mid,
                    inventory=inventory,
                    reading=reading,
                    cfg=cfg,
                    was_halted=state.halted,
                    prev_book_mid=state.prev_book_mid,
                    seconds_to_expiry=seconds_to_expiry,
                    realized_loss_usdc=realized_loss,
                    desk_exposure_usdc=desk_exposure_usdc,
                )
                state.prev_book_mid = book_mid
                state.halted = decision.halted
                state.ticks += 1
                state.last_tick_at = time.time()
                state.last_decision = decision.to_dict()
                state.last_error = None

                if cfg.dry_run:
                    return

                if decision.action == "HALT":
                    await session.commit()
                    await self._cancel_resting(state)
                    return

                token = (
                    await session.execute(select(OutcomeToken).where(OutcomeToken.token_id == cfg.token_id))
                ).scalar_one_or_none()
                if not market or market.status != "ACTIVE" or not token:
                    state.last_error = "Market or token not active"
                    return

                engine = MatchingEngine(broadcaster=broadcast_engine_events)

                # Requote bid if shifted >= tick_size
                await self._sync_side(
                    session, engine, market, token, state, side="BUY", target_px=decision.bid_price, size=decision.quote_size
                )
                # Requote ask if shifted >= tick_size
                await self._sync_side(
                    session, engine, market, token, state, side="SELL", target_px=decision.ask_price, size=decision.quote_size
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            state.last_error = str(exc)[:200]
            logger.warning("MM step error for desk %s: %s", cfg.desk_id, exc)

    async def _sync_side(
        self,
        session: Any,
        engine: MatchingEngine,
        market: Market,
        token: OutcomeToken,
        state: MMRuntimeState,
        *,
        side: str,
        target_px: Decimal | None,
        size: Decimal,
    ) -> None:
        cfg = state.cfg
        is_bid = side == "BUY"
        resting_id = state.resting_bid_id if is_bid else state.resting_ask_id
        resting_px = state.resting_bid_px if is_bid else state.resting_ask_px

        if resting_id and (
            target_px is None or resting_px is None or abs(target_px - resting_px) >= cfg.tick_size
        ):
            existing = (await session.execute(select(Order).where(Order.id == resting_id))).scalar_one_or_none()
            if existing and existing.status in ("OPEN", "PARTIALLY_FILLED"):
                await engine.cancel_order(session, existing, collateral)
                state.orders_cancelled += 1
            resting_id = None
            resting_px = None

        if target_px is not None and resting_id is None and size > 0:
            try:
                order_obj = await engine.submit_order(
                    session=session,
                    user_id=cfg.owner_user_id,
                    market=market,
                    token=token,
                    collateral_service=collateral,
                    side=side,
                    price=target_px,
                    amount=size,
                    order_type="LIMIT",
                    time_in_force="GTC",
                    post_only=True,
                    desk_id=cfg.desk_id,
                )
                if getattr(order_obj, "status", None) in ("OPEN", "PARTIALLY_FILLED"):
                    resting_id = order_obj.id
                    resting_px = target_px
                state.orders_placed += 1
            except OrderRejected as exc:
                state.last_error = str(exc)

        if is_bid:
            state.resting_bid_id = resting_id
            state.resting_bid_px = resting_px
        else:
            state.resting_ask_id = resting_id
            state.resting_ask_px = resting_px


mm_manager = FearGreedMarketMakerManager()
