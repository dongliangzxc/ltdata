"""add status and operator to models

Revision ID: p16a1b2c3d4e5
Revises: p15a1b2c3d4e5
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'p16a1b2c3d4e5'
down_revision = 'p15a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('models', sa.Column(
        'status', sa.String(20), nullable=False, server_default='active',
        comment='active/inactive'
    ))
    op.add_column('models', sa.Column(
        'operator', sa.String(100), nullable=True,
        comment='最后操作人'
    ))


def downgrade():
    op.drop_column('models', 'operator')
    op.drop_column('models', 'status')
