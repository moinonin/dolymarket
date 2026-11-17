"""add_outbox_and_onchain_unique_constraints

Revision ID: a6c66fbf5112
Revises: 48c2a3478340
Create Date: 2026-11-17 19:23:16.586008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6c66fbf5112'
down_revision: Union[str, Sequence[str], None] = '48c2a3478340'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_outbox_token_seq",
        "outbox_events",
        ["token_id", "partition_seq"],
        unique=True,
    )
    op.create_index(
        "ix_collateral_ledger_unique_onchain_ref",
        "collateral_ledger",
        ["reference"],
        unique=True,
        sqlite_where=sa.text("reference LIKE 'onchain:%'"),
        postgresql_where=sa.text("reference LIKE 'onchain:%'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_collateral_ledger_unique_onchain_ref", table_name="collateral_ledger")
    op.drop_index("uq_outbox_token_seq", table_name="outbox_events")
