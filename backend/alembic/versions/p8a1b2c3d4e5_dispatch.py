"""P8 — data dispatch tables

Revision ID: p8a1b2c3d4e5
Revises: p7a1b2c3d4e5
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'p8a1b2c3d4e5'
down_revision = 'p7a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dispatch_rules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('category_code', sa.String(50), nullable=False),
        sa.Column('platform', sa.String(50), nullable=True),
        sa.Column('field', sa.String(50), nullable=False),
        sa.Column('match_type', sa.String(20), nullable=False),
        sa.Column('value', sa.String(200), nullable=False),
        sa.Column('item_name_keyword', sa.String(200), nullable=True),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_dispatch_rules_category_code', 'dispatch_rules', ['category_code'])
    op.create_index('ix_dispatch_rules_priority', 'dispatch_rules', ['priority'])

    op.create_table(
        'dispatch_batches',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('file_id', sa.Integer, sa.ForeignKey('upload_files.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('total_rows', sa.Integer, nullable=True),
        sa.Column('dispatched_rows', sa.Integer, nullable=True),
        sa.Column('unmatched_rows', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_dispatch_batches_file_id', 'dispatch_batches', ['file_id'])

    op.create_table(
        'dispatch_items',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('batch_id', sa.Integer, sa.ForeignKey('dispatch_batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('raw_data_id', sa.Integer, sa.ForeignKey('raw_data.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category_code', sa.String(50), nullable=False),
        sa.Column('matched_rule_id', sa.Integer, nullable=True),
        # soft FK to dispatch_rules.id — intentionally no hard constraint for traceability (rule may be edited/deleted after dispatch)
        sa.UniqueConstraint('batch_id', 'raw_data_id', name='uq_dispatch_items_batch_row'),
    )
    op.create_index('ix_dispatch_items_batch_id', 'dispatch_items', ['batch_id'])
    op.create_index('ix_dispatch_items_category_code', 'dispatch_items', ['category_code'])

    op.add_column('clean_jobs', sa.Column('dispatch_batch_id', sa.Integer, nullable=True))
    op.add_column('clean_jobs', sa.Column('dispatch_category_code', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('clean_jobs', 'dispatch_category_code')
    op.drop_column('clean_jobs', 'dispatch_batch_id')
    op.drop_index('ix_dispatch_items_category_code', table_name='dispatch_items')
    op.drop_index('ix_dispatch_items_batch_id', table_name='dispatch_items')
    op.drop_table('dispatch_items')
    op.drop_index('ix_dispatch_batches_file_id', table_name='dispatch_batches')
    op.drop_table('dispatch_batches')
    op.drop_index('ix_dispatch_rules_priority', table_name='dispatch_rules')
    op.drop_index('ix_dispatch_rules_category_code', table_name='dispatch_rules')
    op.drop_table('dispatch_rules')
