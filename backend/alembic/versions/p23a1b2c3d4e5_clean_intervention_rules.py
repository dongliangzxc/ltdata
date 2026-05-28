"""P23: add clean intervention rules

Revision ID: p23a1b2c3d4e5
Revises: p22a1b2c3d4e5
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'p23a1b2c3d4e5'
down_revision = 'p22a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intervention_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category_code', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('conditions', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint("action IN ('filter', 'allow')", name='ck_intervention_rule_action'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_intervention_rules_id'), 'intervention_rules', ['id'], unique=False)
    op.create_index(op.f('ix_intervention_rules_category_code'), 'intervention_rules', ['category_code'], unique=False)
    op.add_column('filtered_items', sa.Column('intervention_rule_id', sa.Integer(), nullable=True))
    op.add_column('filtered_items', sa.Column('intervention_rule_name', sa.String(length=100), nullable=True))
    op.add_column('filtered_items', sa.Column('matched_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_filtered_items_intervention_rule_id',
        'filtered_items',
        'intervention_rules',
        ['intervention_rule_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.execute('DELETE FROM noise_words')


def downgrade() -> None:
    op.drop_constraint('fk_filtered_items_intervention_rule_id', 'filtered_items', type_='foreignkey')
    op.drop_column('filtered_items', 'matched_reason')
    op.drop_column('filtered_items', 'intervention_rule_name')
    op.drop_column('filtered_items', 'intervention_rule_id')
    op.drop_index(op.f('ix_intervention_rules_category_code'), table_name='intervention_rules')
    op.drop_index(op.f('ix_intervention_rules_id'), table_name='intervention_rules')
    op.drop_table('intervention_rules')
