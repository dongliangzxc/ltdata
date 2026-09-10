"""item_url_mappings: add category_code column

Revision ID: p51a1b2c3d4e5
Revises: p50a1b2c3d4e5
Create Date: 2026-09-10

URL 映射库映射记录新增品类归属列：导入时记录用户选择的品类，
型号为空/未匹配的占位记录也能展示品类；型号匹配后用型号品类兜底。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p51a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p50a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "item_url_mappings",
        sa.Column("category_code", sa.String(50), nullable=True),
    )
    op.create_index("ix_item_url_mappings_category_code", "item_url_mappings", ["category_code"])


def downgrade() -> None:
    op.drop_index("ix_item_url_mappings_category_code", table_name="item_url_mappings")
    op.drop_column("item_url_mappings", "category_code")