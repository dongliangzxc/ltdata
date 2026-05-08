"""add item_url to item_url_mappings

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-09

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'item_url_mappings',
        sa.Column('item_url', sa.String(500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('item_url_mappings', 'item_url')
