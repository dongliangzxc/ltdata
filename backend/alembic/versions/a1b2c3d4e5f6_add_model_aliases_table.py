"""add model_aliases table

Revision ID: a1b2c3d4e5f6
Revises: 8c8de0f7ebf8
Create Date: 2026-04-29

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8c8de0f7ebf8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'model_aliases',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('model_id',   sa.Integer(),     nullable=False),
        sa.Column('alias_code', sa.String(200),   nullable=False),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['model_id'], ['models.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('alias_code', name='uq_alias_code'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        comment='型号别名',
    )
    op.create_index('idx_alias_model', 'model_aliases', ['model_id'])


def downgrade() -> None:
    op.drop_index('idx_alias_model', table_name='model_aliases')
    op.drop_table('model_aliases')
