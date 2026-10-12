"""item_exclusions: 人工排除沉淀库

Revision ID: p58a1b2c3d4e5
Revises: p57a1b2c3d4e5
Create Date: 2026-10-12

人工排除的商品写入本表，后续同品类清洗任务在匹配阶段按
(platform, item_id) 优先、规范化标题 item_name_norm 兜底自动沿用排除。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p58a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p57a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(50), nullable=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("item_id", sa.String(100), nullable=True),
        sa.Column("item_url", sa.String(500), nullable=True),
        sa.Column("item_name", sa.Text(), nullable=True),
        sa.Column("item_name_norm", sa.String(500), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("source", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_item_exclusions_category_code", "item_exclusions", ["category_code"])
    op.create_index("idx_item_excl_cat_item", "item_exclusions", ["category_code", "platform", "item_id"])
    op.create_index("idx_item_excl_cat_name", "item_exclusions", ["category_code", "item_name_norm"])


def downgrade() -> None:
    op.drop_index("idx_item_excl_cat_name", table_name="item_exclusions")
    op.drop_index("idx_item_excl_cat_item", table_name="item_exclusions")
    op.drop_index("ix_item_exclusions_category_code", table_name="item_exclusions")
    op.drop_table("item_exclusions")
