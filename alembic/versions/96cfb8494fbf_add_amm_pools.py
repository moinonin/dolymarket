"""add_amm_pools

Revision ID: 96cfb8494fbf
Revises: c5f26e9c2141
Create Date: 2026-11-17 14:44:40.970408

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96cfb8494fbf'
down_revision: Union[str, Sequence[str], None] = 'c5f26e9c2141'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'amm_pools',
        sa.Column('market_id', sa.String(length=36), nullable=False),
        sa.Column('b', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('q_yes', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('q_no', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('pool_usdc', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('fees_collected_usdc', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('total_lp_shares', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('fee_bps', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['market_id'], ['markets.id'], name='fk_amm_pools_market_id'),
        sa.PrimaryKeyConstraint('market_id'),
    )
    op.create_table(
        'amm_lp_positions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('market_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('lp_shares', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('deposited_usdc', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['market_id'], ['amm_pools.market_id'], name='fk_amm_lp_market_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_amm_lp_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_amm_lp_positions_market_id', 'amm_lp_positions', ['market_id'], unique=False)
    op.create_index('ix_amm_lp_positions_user_id', 'amm_lp_positions', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_amm_lp_positions_user_id', table_name='amm_lp_positions')
    op.drop_index('ix_amm_lp_positions_market_id', table_name='amm_lp_positions')
    op.drop_table('amm_lp_positions')
    op.drop_table('amm_pools')
