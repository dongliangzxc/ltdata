"""add disable fields to match_results

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-29

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'match_results',
        sa.Column('is_disabled', sa.SmallInteger(), nullable=False, server_default='0',
                  comment='1=禁用 0=正常'),
    )
    op.add_column(
        'match_results',
        sa.Column('disable_reason', sa.String(100), nullable=True,
                  comment='禁用原因: avg_price/商用/配件/其他'),
    )
    op.create_index('idx_match_results_disabled', 'match_results', ['is_disabled'])


def downgrade() -> None:
    op.drop_index('idx_match_results_disabled', table_name='match_results')
    op.drop_column('match_results', 'disable_reason')
    op.drop_column('match_results', 'is_disabled')
