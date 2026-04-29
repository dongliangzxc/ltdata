"""add item_url_mappings table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'item_url_mappings',
        sa.Column('id',         sa.Integer(),      primary_key=True, autoincrement=True),
        sa.Column('platform',   sa.String(20),     nullable=False, comment='jd/tmall/taobao/suning'),
        sa.Column('item_id',    sa.String(100),    nullable=False, comment='从URL提取的商品ID'),
        sa.Column('model_id',   sa.Integer(),      nullable=False, comment='FK → models.id'),
        sa.Column('price',      sa.Numeric(10, 2), nullable=True,  comment='单价'),
        sa.Column('created_at', sa.DateTime(),     nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(),     nullable=False, server_default=sa.text('NOW()'),
                  onupdate=sa.text('NOW()')),
        sa.UniqueConstraint('platform', 'item_id', name='uq_platform_item'),
        sa.ForeignKeyConstraint(['model_id'], ['models.id']),
    )
    op.create_index('idx_url_mappings_model', 'item_url_mappings', ['model_id'])


def downgrade() -> None:
    op.drop_index('idx_url_mappings_model', table_name='item_url_mappings')
    op.drop_table('item_url_mappings')
