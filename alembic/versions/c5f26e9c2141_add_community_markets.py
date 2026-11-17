"""add_community_markets

Revision ID: c5f26e9c2141
Revises: fbc302375200
Create Date: 2026-11-17 14:35:47.007830

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f26e9c2141'
down_revision: Union[str, Sequence[str], None] = 'fbc302375200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('events', sa.Column('tier', sa.String(length=20), nullable=False, server_default='OFFICIAL'))
    op.add_column('events', sa.Column('creator_user_id', sa.String(length=36), nullable=True))
    op.create_index('ix_events_creator_user_id', 'events', ['creator_user_id'], unique=False)
    op.create_index('ix_events_tier', 'events', ['tier'], unique=False)

    op.add_column('markets', sa.Column('tier', sa.String(length=20), nullable=False, server_default='OFFICIAL'))
    op.add_column('markets', sa.Column('creator_user_id', sa.String(length=36), nullable=True))
    op.add_column('markets', sa.Column('resolution_criteria', sa.Text(), nullable=True))
    op.add_column('markets', sa.Column('liquidity_funded_usdc', sa.Numeric(precision=18, scale=4), nullable=False, server_default='0'))
    op.create_index('ix_markets_creator_user_id', 'markets', ['creator_user_id'], unique=False)
    op.create_index('ix_markets_tier', 'markets', ['tier'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_markets_tier', table_name='markets')
    op.drop_index('ix_markets_creator_user_id', table_name='markets')
    op.drop_column('markets', 'liquidity_funded_usdc')
    op.drop_column('markets', 'resolution_criteria')
    op.drop_column('markets', 'creator_user_id')
    op.drop_column('markets', 'tier')

    op.drop_index('ix_events_tier', table_name='events')
    op.drop_index('ix_events_creator_user_id', table_name='events')
    op.drop_column('events', 'creator_user_id')
    op.drop_column('events', 'tier')
