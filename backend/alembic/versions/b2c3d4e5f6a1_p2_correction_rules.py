"""P2: add correction_rules table

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'correction_rules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('category_code', sa.String(100), nullable=True),
        sa.Column('brand_code', sa.String(100), nullable=True),
        sa.Column('model_id', sa.Integer, nullable=True),
        sa.Column('attr_name', sa.String(200), nullable=True),
        sa.Column('attr_value', sa.String(200), nullable=True),
        sa.Column('target', sa.Enum('sales_qty', 'sales_amount', 'both'), nullable=False),
        sa.Column('rule_type', sa.Enum('multiply', 'offset'), nullable=False),
        sa.Column('value', sa.Numeric(12, 4), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('is_active', sa.SmallInteger, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('correction_rules')
