"""Add parent_code and sort_order to categories

Revision ID: p19a1b2c3d4e5
Revises: p18a1b2c3d4e5
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p19a1b2c3d4e5'
down_revision = 'p18a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('categories', sa.Column(
        'parent_code', sa.String(50), nullable=True,
        comment='父品类码，NULL 表示顶级品类',
    ))
    op.add_column('categories', sa.Column(
        'sort_order', sa.Integer(), nullable=False, server_default='0',
        comment='排序值，越小越靠前',
    ))


def downgrade():
    op.drop_column('categories', 'sort_order')
    op.drop_column('categories', 'parent_code')
