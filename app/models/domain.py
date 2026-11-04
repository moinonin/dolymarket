"""Domain persistence models for the prediction market platform.

Covers all nine primary domain entities:
User, CollateralAccount, Event, Market, OutcomeToken, Order, TradeFill,
Position, OracleDispute.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    api_key = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)

    collateral_account = relationship(
        "CollateralAccount", back_populates="user", uselist=False
    )


class CollateralAccount(Base):
    __tablename__ = "collateral_accounts"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String(36), ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    balance = Column(Numeric(18, 4), default=0)
    locked_balance = Column(Numeric(18, 4), default=0)
    currency = Column(String(10), default="USDC")

    user = relationship("User", back_populates="collateral_account")
    ledger = relationship(
        "CollateralLedgerEntry", back_populates="account", cascade="all, delete-orphan"
    )


class CollateralLedgerEntry(Base):
    """Ledger trail for deposits, withdrawals, locks, releases, fees and payouts."""

    __tablename__ = "collateral_ledger"

    id = Column(String(36), primary_key=True, default=_uuid)
    account_id = Column(
        String(36), ForeignKey("collateral_accounts.id"), nullable=False, index=True
    )
    kind = Column(String(32), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    reference = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc, index=True)

    account = relationship("CollateralAccount", back_populates="ledger")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=_uuid)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, index=True)
    tags = Column(JSON, default=list)
    status = Column(String(20), nullable=False, default="ACTIVE", index=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    total_volume = Column(Numeric(18, 4), default=0)
    created_at = Column(DateTime(timezone=True), default=_now_utc)

    markets = relationship("Market", back_populates="event", cascade="all, delete-orphan")


class Market(Base):
    __tablename__ = "markets"

    id = Column(String(36), primary_key=True, default=_uuid)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    condition_id = Column(String(66), unique=True, nullable=False, index=True)
    question = Column(String(500), nullable=False)
    outcomes = Column(JSON, nullable=False)
    tick_size = Column(Numeric(6, 4), default=0.01)
    min_order_size = Column(Numeric(12, 4), default=5.0)
    status = Column(String(20), nullable=False, default="ACTIVE", index=True)
    neg_risk = Column(Boolean, default=False)
    winning_outcome_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)

    event = relationship("Event", back_populates="markets")
    tokens = relationship(
        "OutcomeToken", back_populates="market", cascade="all, delete-orphan"
    )


class OutcomeToken(Base):
    __tablename__ = "outcome_tokens"

    id = Column(String(36), primary_key=True, default=_uuid)
    token_id = Column(String(100), unique=True, nullable=False, index=True)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    outcome_index = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)

    market = relationship("Market", back_populates="tokens")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_market", "user_id", "market_id"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    token_id = Column(
        String(100), ForeignKey("outcome_tokens.token_id"), nullable=False, index=True
    )
    side = Column(String(10), nullable=False)
    type = Column(String(10), nullable=False, default="LIMIT")
    price = Column(Numeric(6, 4), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    filled_amount = Column(Numeric(18, 4), default=0)
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    time_in_force = Column(String(10), default="GTC")
    post_only = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc, index=True)


class TradeFill(Base):
    __tablename__ = "trade_fills"

    id = Column(String(36), primary_key=True, default=_uuid)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    token_id = Column(String(100), nullable=False, index=True)
    maker_order_id = Column(String(36), ForeignKey("orders.id"), nullable=False)
    taker_order_id = Column(String(36), ForeignKey("orders.id"), nullable=False)
    maker_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    taker_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    price = Column(Numeric(6, 4), nullable=False)
    shares = Column(Numeric(18, 4), nullable=False)
    maker_fee = Column(Numeric(18, 4), default=0)
    taker_fee = Column(Numeric(18, 4), default=0)
    timestamp = Column(DateTime(timezone=True), default=_now_utc, index=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "token_id", name="uq_position_user_token"),
        Index("ix_positions_user", "user_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    token_id = Column(String(100), nullable=False, index=True)
    shares = Column(Numeric(18, 4), default=0)
    locked_shares = Column(Numeric(18, 4), default=0)
    avg_entry_price = Column(Numeric(6, 4), default=0)
    realized_pnl = Column(Numeric(18, 4), default=0)
    is_settled = Column(Boolean, default=False)
    claimed = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc)


class OracleDispute(Base):
    __tablename__ = "oracle_disputes"

    id = Column(String(36), primary_key=True, default=_uuid)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    proposed_outcome_index = Column(Integer, nullable=False)
    proposer_address = Column(String(100), nullable=False)
    bond_amount = Column(Numeric(18, 4), nullable=False)
    dispute_deadline = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), default="PROPOSED", index=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
