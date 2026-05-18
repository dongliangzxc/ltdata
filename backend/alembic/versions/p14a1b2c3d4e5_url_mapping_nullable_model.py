"""item_url_mappings.model_id 改为可空，支持 URL-only 映射

Revision ID: p14a1b2c3d4e5
Revises: p13a1b2c3d4e5
Create Date: 2026-05-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p14a1b2c3d4e5'
down_revision = 'p13a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('item_url_mappings', 'model_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.alter_column('item_url_mappings', 'model_id', existing_type=sa.Integer(), nullable=False)
