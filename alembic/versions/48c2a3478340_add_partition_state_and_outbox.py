"""add_partition_state_and_outbox

Revision ID: 48c2a3478340
Revises: 887147b0e5f3
Create Date: 2026-11-17 17:54:35.496970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48c2a3478340'
down_revision: Union[str, Sequence[str], None] = '887147b0e5f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "token_partition_states",
        sa.Column("token_id", sa.String(length=100), nullable=False),
        sa.Column("leader_id", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sequence_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("token_id"),
    )
    op.create_index("ix_token_partition_states_leader_id", "token_partition_states", ["leader_id"], unique=False)

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_id", sa.String(length=100), nullable=True),
        sa.Column("partition_seq", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_token_id", "outbox_events", ["token_id"], unique=False)
    op.create_index("ix_outbox_events_partition_seq", "outbox_events", ["partition_seq"], unique=False)
    op.create_index("ix_outbox_events_channel", "outbox_events", ["channel"], unique=False)
    op.create_index("ix_outbox_events_published", "outbox_events", ["published"], unique=False)
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("outbox_events")
    op.drop_table("token_partition_states")
