"""P13 — historical_mappings.model_id nullable

Revision ID: p13a1b2c3d4e5
Revises: p12a1b2c3d4e5
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'p13a1b2c3d4e5'
down_revision = 'p12a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'historical_mappings', 'model_id',
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        'historical_mappings', 'model_id',
        existing_type=sa.Integer(),
        nullable=False,
    )
