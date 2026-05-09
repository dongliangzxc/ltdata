"""P1: add category_lv0, calc_price, corrected fields to cleaned_data and published_items

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cleaned_data ────────────────────────────────────────────
    op.add_column('cleaned_data', sa.Column('category_lv0', sa.String(100), nullable=True))
    op.add_column('cleaned_data', sa.Column('calc_price', sa.Numeric(12, 2), nullable=True))
    op.add_column('cleaned_data', sa.Column('corrected_sales_qty', sa.Integer, nullable=True))
    op.add_column('cleaned_data', sa.Column('corrected_sales_amount', sa.Numeric(14, 2), nullable=True))
    # ── published_items（跨库 DDL，MySQL 支持 database.table 语法）───
    op.execute("ALTER TABLE luotu_analytics.published_items ADD COLUMN category_lv0 VARCHAR(100) NULL")
    op.execute("ALTER TABLE luotu_analytics.published_items ADD COLUMN calc_price DECIMAL(12,2) NULL")
    op.execute("ALTER TABLE luotu_analytics.published_items ADD COLUMN corrected_sales_qty INT NULL")
    op.execute("ALTER TABLE luotu_analytics.published_items ADD COLUMN corrected_sales_amount DECIMAL(14,2) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE luotu_analytics.published_items DROP COLUMN corrected_sales_amount")
    op.execute("ALTER TABLE luotu_analytics.published_items DROP COLUMN corrected_sales_qty")
    op.execute("ALTER TABLE luotu_analytics.published_items DROP COLUMN calc_price")
    op.execute("ALTER TABLE luotu_analytics.published_items DROP COLUMN category_lv0")
    op.drop_column('cleaned_data', 'corrected_sales_amount')
    op.drop_column('cleaned_data', 'corrected_sales_qty')
    op.drop_column('cleaned_data', 'calc_price')
    op.drop_column('cleaned_data', 'category_lv0')
