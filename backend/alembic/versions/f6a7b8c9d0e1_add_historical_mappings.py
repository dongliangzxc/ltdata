"""add historical_mappings table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'historical_mappings',
        sa.Column('id',           sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column('platform',     sa.String(50),   nullable=False),
        sa.Column('item_id',      sa.String(200),  nullable=False),
        sa.Column('model_id',     sa.Integer(),    nullable=False),
        sa.Column('import_batch', sa.String(100),  nullable=True),
        sa.Column('created_at',   sa.DateTime(),   nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at',   sa.DateTime(),   nullable=False, server_default=sa.text('NOW()'),
                  onupdate=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['model_id'], ['models.id']),
        sa.UniqueConstraint('platform', 'item_id', name='uq_hist_platform_item'),
    )
    op.create_index('idx_hist_platform_item', 'historical_mappings', ['platform', 'item_id'])
    op.create_index('idx_hist_import_batch',  'historical_mappings', ['import_batch'])


def downgrade() -> None:
    op.drop_index('idx_hist_import_batch',  table_name='historical_mappings')
    op.drop_index('idx_hist_platform_item', table_name='historical_mappings')
    op.drop_table('historical_mappings')
