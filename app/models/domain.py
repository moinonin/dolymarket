"""Domain persistence models for the Dolymarket prediction market platform.

Covers the primary domain entities:
User, CollateralAccount, Event, Market, OutcomeToken, Order, TradeFill,
Position, OracleDispute, plus idempotency records for safe order retries and
the federated-auth tables (linked OAuth accounts, WebAuthn passkeys,
ceremony challenges and one-time login exchange codes).
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
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from decimal import Decimal
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
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc)

    collateral_account = relationship(
        "CollateralAccount", back_populates="user", uselist=False
    )
    oauth_accounts = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )
    passkeys = relationship(
        "PasskeyCredential", back_populates="user", cascade="all, delete-orphan"
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
    desk_id = Column(String(36), ForeignKey("desks.id"), nullable=True, index=True)
    copy_source_fill_id = Column(
        String(36), ForeignKey("trade_fills.id"), nullable=True, index=True
    )
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
    sequence_id = Column(Integer, nullable=True, index=True)
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


class IdempotencyRecord(Base):
    """Cached response for a client-supplied ``X-Idempotency-Key``.

    The unique ``(user_id, key)`` pair guarantees that a retried order can
    never be matched twice. ``request_hash`` detects accidental key reuse with
    a different payload and returns HTTP 409 instead of replaying stale data.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status_code = Column(Integer, nullable=False, default=201)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now_utc, index=True)


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


class OAuthAccount(Base):
    """A third-party identity linked to a local account.

    ``(provider, provider_user_id)`` is unique: the same Google/Microsoft/
    Apple subject can only ever map to one Dolymarket account. Linking by
    verified e-mail is allowed once, so an account created with a password can
    later be connected to a provider without creating a duplicate user.
    """

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_provider_subject"
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, index=True)
    provider_user_id = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc)

    user = relationship("User", back_populates="oauth_accounts")


class PasskeyCredential(Base):
    """A registered WebAuthn credential (passkey).

    ``public_key`` stores the COSE-encoded key exactly as produced by the
    WebAuthn registration ceremony so assertions can be verified later.
    ``sign_count`` is the authenticator's counter and is used for clone
    detection.
    """

    __tablename__ = "passkey_credentials"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    credential_id = Column(String(255), unique=True, nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    aaguid = Column(String(64), nullable=True)
    transports = Column(JSON, nullable=True)
    backed_up = Column(Boolean, nullable=False, default=False)
    device_type = Column(String(32), nullable=True)
    label = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="passkeys")


class PasskeyChallenge(Base):
    """Short-lived WebAuthn ceremony challenge.

    The challenge is bound to the ceremony kind (and, for registration, to the
    authenticated user) so a challenge can never be replayed for the other
    ceremony.
    """

    __tablename__ = "passkey_challenges"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    challenge = Column(String(255), unique=True, nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)


class AuthExchangeCode(Base):
    """One-time code handed to the browser after a federated login.

    The callback never returns a JWT through the URL. It mints a short-lived,
    single-use code that the frontend redeems exactly once at
    ``POST /api/v1/auth/oauth/exchange``.
    """

    __tablename__ = "auth_exchange_codes"

    id = Column(String(36), primary_key=True, default=_uuid)
    code = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)


class Desk(Base):
    __tablename__ = "desks"
    __table_args__ = (UniqueConstraint("owner_user_id", name="uq_desk_owner"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    slug = Column(String(96), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="DRAFT", index=True)
    review_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="desk")
    followers = relationship("DeskFollower", back_populates="desk", cascade="all, delete-orphan")
    positions = relationship("DeskPosition", back_populates="desk", cascade="all, delete-orphan")
    copy_jobs = relationship("CopyJob", back_populates="desk", cascade="all, delete-orphan")


class DeskFollower(Base):
    __tablename__ = "desk_followers"
    __table_args__ = (
        UniqueConstraint("desk_id", "follower_user_id", name="uq_follow_desk_user"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    desk_id = Column(String(36), ForeignKey("desks.id"), nullable=False, index=True)
    follower_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    copy_ratio = Column(Numeric(5, 4), nullable=False, default=Decimal("0.2500"))
    per_market_cap_usdc = Column(Numeric(18, 4), nullable=False, default=Decimal("50.0000"))
    max_per_market_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("20.00"))
    max_total_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("25.00"))
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc)

    desk = relationship("Desk", back_populates="followers")


class DeskPosition(Base):
    __tablename__ = "desk_positions"
    __table_args__ = (UniqueConstraint("desk_id", "token_id", name="uq_desk_token"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    desk_id = Column(String(36), ForeignKey("desks.id"), nullable=False, index=True)
    market_id = Column(String(36), ForeignKey("markets.id"), nullable=False, index=True)
    token_id = Column(String(100), nullable=False, index=True)
    outcome_index = Column(Integer, nullable=False, default=0)
    shares = Column(Numeric(18, 4), nullable=False, default=0)
    avg_entry_price = Column(Numeric(6, 4), nullable=False, default=0)
    realized_pnl_usdc = Column(Numeric(18, 4), nullable=False, default=0)
    settled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc)

    desk = relationship("Desk", back_populates="positions")


class CopyJob(Base):
    __tablename__ = "copy_jobs"
    __table_args__ = (
        UniqueConstraint("follower_user_id", "source_fill_id", name="uq_copy_follower_fill"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    desk_id = Column(String(36), ForeignKey("desks.id"), nullable=False, index=True)
    follower_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    source_fill_id = Column(String(36), ForeignKey("trade_fills.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    copy_ratio = Column(Numeric(5, 4), nullable=False)
    requested_shares = Column(Numeric(18, 4), nullable=False, default=0)
    requested_cost_usdc = Column(Numeric(18, 4), nullable=False, default=0)
    filled_shares = Column(Numeric(18, 4), nullable=False, default=0)
    filled_cost_usdc = Column(Numeric(18, 4), nullable=False, default=0)
    limit_breached = Column(Boolean, nullable=False, default=False)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now_utc)
    updated_at = Column(DateTime(timezone=True), default=_now_utc, onupdate=_now_utc)

    desk = relationship("Desk", back_populates="copy_jobs")


# One-to-one relationship convenience (added here so the model graph is complete).
User.desk = relationship("Desk", back_populates="owner", uselist=False)
