"""Add data_region, data_year, data_month to upload_files

Revision ID: p17a1b2c3d4e5
Revises: p16a1b2c3d4e5
Create Date: 2026-05-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p17a1b2c3d4e5'
down_revision = 'p16a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('upload_files', sa.Column(
        'data_region', sa.String(20), nullable=True,
        comment='domestic/overseas',
    ))
    op.add_column('upload_files', sa.Column(
        'data_year', sa.SmallInteger(), nullable=True,
        comment='数据年份，e.g. 2026',
    ))
    op.add_column('upload_files', sa.Column(
        'data_month', sa.SmallInteger(), nullable=True,
        comment='数据月份 1-12',
    ))


def downgrade():
    op.drop_column('upload_files', 'data_month')
    op.drop_column('upload_files', 'data_year')
    op.drop_column('upload_files', 'data_region')
