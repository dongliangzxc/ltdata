"""Add price audit and sales adjustment fields

Revision ID: p20a1b2c3d4e5
Revises: p19a1b2c3d4e5
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p20a1b2c3d4e5'
down_revision = 'p19a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('match_results', sa.Column(
        'price_flag', sa.String(20), nullable=True,
        comment='ok/high/low/no_history',
    ))
    op.add_column('match_results', sa.Column(
        'price_ref', sa.Numeric(10, 2), nullable=True,
        comment='参考均价',
    ))
    op.add_column('match_results', sa.Column(
        'sales_coefficient', sa.Numeric(6, 4), nullable=True,
        comment='销量调整系数',
    ))


def downgrade():
    op.drop_column('match_results', 'sales_coefficient')
    op.drop_column('match_results', 'price_ref')
    op.drop_column('match_results', 'price_flag')
