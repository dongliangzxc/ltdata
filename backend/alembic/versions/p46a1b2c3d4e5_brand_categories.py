"""brand_categories: direct brand-category association

Revision ID: p46a1b2c3d4e5
Revises: p45a1b2c3d4e5
Create Date: 2026-09-04

一个品牌可对应多个品类（如汉王同时属于电子纸平板和词典笔）。
品牌品类展示/筛选 = 直接指派（brand_categories）∪ 型号推导 的并集。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p46a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p45a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("brand_code", sa.String(100), nullable=False),
        sa.Column("category_code", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("brand_code", "category_code", name="uq_brand_category"),
    )
    op.create_index("ix_brand_categories_brand", "brand_categories", ["brand_code"])
    op.create_index("ix_brand_categories_category", "brand_categories", ["category_code"])


def downgrade() -> None:
    op.drop_index("ix_brand_categories_category", table_name="brand_categories")
    op.drop_index("ix_brand_categories_brand", table_name="brand_categories")
    op.drop_table("brand_categories")