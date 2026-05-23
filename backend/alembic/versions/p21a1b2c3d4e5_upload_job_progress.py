"""P21: add upload confirm job progress fields

Revision ID: p21a1b2c3d4e5
Revises: p20a1b2c3d4e5
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa


revision = 'p21a1b2c3d4e5'
down_revision = 'p20a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('upload_confirm_jobs', sa.Column('filename', sa.String(500), nullable=True))
    op.add_column('upload_confirm_jobs', sa.Column('stage', sa.String(30), nullable=False, server_default='pending'))
    op.add_column('upload_confirm_jobs', sa.Column('stage_label', sa.String(100), nullable=False, server_default='等待处理'))
    op.add_column('upload_confirm_jobs', sa.Column('total_rows', sa.Integer(), nullable=True))
    op.add_column('upload_confirm_jobs', sa.Column('processed_rows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('upload_confirm_jobs', sa.Column('inserted_rows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('upload_confirm_jobs', sa.Column('skipped_rows', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('upload_confirm_jobs', 'skipped_rows')
    op.drop_column('upload_confirm_jobs', 'inserted_rows')
    op.drop_column('upload_confirm_jobs', 'processed_rows')
    op.drop_column('upload_confirm_jobs', 'total_rows')
    op.drop_column('upload_confirm_jobs', 'stage_label')
    op.drop_column('upload_confirm_jobs', 'stage')
    op.drop_column('upload_confirm_jobs', 'filename')
