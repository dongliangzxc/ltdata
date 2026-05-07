"""add attr_rules and match_result_attrs tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── attr_rules ────────────────────────────────────────────
    op.create_table(
        'attr_rules',
        sa.Column('id',            sa.Integer(),      primary_key=True, autoincrement=True),
        sa.Column('keyword',       sa.String(200),    nullable=False),
        sa.Column('match_type',    sa.String(20),     nullable=False, server_default='contains'),
        sa.Column('attr_name',     sa.String(100),    nullable=False),
        sa.Column('attr_value',    sa.String(200),    nullable=False),
        sa.Column('category_code', sa.String(100),    nullable=True),
        sa.Column('priority',      sa.Integer(),      nullable=False, server_default='100'),
        sa.Column('is_active',     sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('created_by',    sa.String(50),     nullable=True),
        sa.Column('created_at',    sa.DateTime(),     nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('keyword', 'attr_name', 'category_code', name='uq_attr_rule'),
    )
    op.create_index('idx_attr_rules_priority', 'attr_rules', ['priority'])
    op.create_index('idx_attr_rules_category', 'attr_rules', ['category_code'])

    # ── match_result_attrs ────────────────────────────────────
    op.create_table(
        'match_result_attrs',
        sa.Column('id',               sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column('match_result_id',  sa.Integer(),   nullable=False),
        sa.Column('attr_name',        sa.String(100), nullable=False),
        sa.Column('attr_value',       sa.String(200), nullable=False),
        sa.Column('rule_id',          sa.Integer(),   nullable=True),
        sa.Column('created_at',       sa.DateTime(),  nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['match_result_id'], ['match_results.id']),
        sa.ForeignKeyConstraint(['rule_id'],          ['attr_rules.id']),
        sa.UniqueConstraint('match_result_id', 'attr_name', name='uq_mr_attr_name'),
    )
    op.create_index('idx_mr_attrs_result_id', 'match_result_attrs', ['match_result_id'])


def downgrade() -> None:
    op.drop_index('idx_mr_attrs_result_id', table_name='match_result_attrs')
    op.drop_table('match_result_attrs')
    op.drop_index('idx_attr_rules_category', table_name='attr_rules')
    op.drop_index('idx_attr_rules_priority', table_name='attr_rules')
    op.drop_table('attr_rules')
