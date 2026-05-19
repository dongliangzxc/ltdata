"""Add source, data_year, data_month to item_url_mappings

Revision ID: p18a1b2c3d4e5
Revises: p17a1b2c3d4e5
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p18a1b2c3d4e5'
down_revision = 'p17a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('item_url_mappings', sa.Column(
        'source', sa.String(30), nullable=True,
        comment='model_db_import/manual/match_confirm/url_import',
    ))
    op.add_column('item_url_mappings', sa.Column(
        'data_year', sa.SmallInteger(), nullable=True,
        comment='关联的上传年份',
    ))
    op.add_column('item_url_mappings', sa.Column(
        'data_month', sa.SmallInteger(), nullable=True,
        comment='关联的上传月份',
    ))


def downgrade():
    op.drop_column('item_url_mappings', 'data_month')
    op.drop_column('item_url_mappings', 'data_year')
    op.drop_column('item_url_mappings', 'source')
