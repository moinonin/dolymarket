"""add_oracle_feed_and_dispute_evidence

Revision ID: 887147b0e5f3
Revises: 96cfb8494fbf
Create Date: 2026-11-17 16:08:22.093718

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '887147b0e5f3'
down_revision: Union[str, Sequence[str], None] = '96cfb8494fbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("markets", sa.Column("oracle_feed", sa.String(length=120), nullable=True))
    op.add_column("oracle_disputes", sa.Column("evidence_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("oracle_disputes", "evidence_json")
    op.drop_column("markets", "oracle_feed")
