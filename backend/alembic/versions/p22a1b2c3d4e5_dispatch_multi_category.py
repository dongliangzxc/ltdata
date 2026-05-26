"""P22: allow dispatch rows in multiple categories

Revision ID: p22a1b2c3d4e5
Revises: p21a1b2c3d4e5
Create Date: 2026-05-26
"""
from alembic import op


revision = 'p22a1b2c3d4e5'
down_revision = 'p21a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uq_dispatch_items_batch_row', 'dispatch_items', type_='unique')
    op.create_unique_constraint(
        'uq_dispatch_items_batch_row_category',
        'dispatch_items',
        ['batch_id', 'raw_data_id', 'category_code'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_dispatch_items_batch_row_category', 'dispatch_items', type_='unique')
    op.create_unique_constraint(
        'uq_dispatch_items_batch_row',
        'dispatch_items',
        ['batch_id', 'raw_data_id'],
    )
