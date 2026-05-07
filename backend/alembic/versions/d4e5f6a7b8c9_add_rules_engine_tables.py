"""add rules engine tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── noise_words ───────────────────────────────────────────
    op.create_table(
        'noise_words',
        sa.Column('id',          sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('keyword',     sa.String(200),   nullable=False),
        sa.Column('match_field', sa.String(20),    nullable=False, server_default='item_name'),
        sa.Column('is_active',   sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by',  sa.String(50),    nullable=True),
        sa.Column('created_at',  sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('keyword', 'match_field', name='uq_noise_keyword_field'),
    )

    # ── filtered_items ────────────────────────────────────────
    op.create_table(
        'filtered_items',
        sa.Column('id',              sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('raw_data_id',     sa.Integer(),     nullable=True),
        sa.Column('clean_job_id',    sa.Integer(),     nullable=True),
        sa.Column('matched_keyword', sa.String(200),   nullable=True),
        sa.Column('is_recovered',    sa.SmallInteger(),nullable=False, server_default='0'),
        sa.Column('recovered_at',    sa.DateTime(),    nullable=True),
        sa.Column('created_at',      sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['raw_data_id'],  ['raw_data.id']),
        sa.ForeignKeyConstraint(['clean_job_id'], ['clean_jobs.id']),
    )
    op.create_index('idx_filtered_items_job', 'filtered_items', ['clean_job_id'])

    # ── brand_aliases ─────────────────────────────────────────
    op.create_table(
        'brand_aliases',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('alias_name', sa.String(200),   nullable=False, unique=True),
        sa.Column('brand_code', sa.String(100),   nullable=False),
        sa.Column('is_active',  sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(50),    nullable=True),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
    )

    # ── match_rules ───────────────────────────────────────────
    op.create_table(
        'match_rules',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('keyword',    sa.String(200),   nullable=False, unique=True),
        sa.Column('match_type', sa.String(20),    nullable=False, server_default='contains'),
        sa.Column('model_id',   sa.Integer(),     nullable=False),
        sa.Column('priority',   sa.Integer(),     nullable=False, server_default='100'),
        sa.Column('is_active',  sa.SmallInteger(),nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(50),    nullable=True),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['model_id'], ['models.id']),
    )
    op.create_index('idx_match_rules_priority', 'match_rules', ['priority'])

    # ── 已有表字段扩展 ────────────────────────────────────────
    op.add_column('cleaned_data',  sa.Column('is_recovered',    sa.SmallInteger(), nullable=False, server_default='0'))
    op.add_column('match_results', sa.Column('brand_identified', sa.SmallInteger(), nullable=False, server_default='1'))
    op.add_column('clean_jobs',    sa.Column('row_filtered',     sa.Integer(),      nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('clean_jobs',    'row_filtered')
    op.drop_column('match_results', 'brand_identified')
    op.drop_column('cleaned_data',  'is_recovered')
    op.drop_index('idx_match_rules_priority', table_name='match_rules')
    op.drop_table('match_rules')
    op.drop_table('brand_aliases')
    op.drop_index('idx_filtered_items_job', table_name='filtered_items')
    op.drop_table('filtered_items')
    op.drop_table('noise_words')
