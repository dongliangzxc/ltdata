"""brands: add brand_alias_name column

Revision ID: p36a1b2c3d4e5
Revises: p35a1b2c3d4e5
Create Date: 2026-07-16

将品牌编辑弹窗里的「品牌别名」落到 brands 主表，避免与 brand_aliases 写法别名列表混用。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p36a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p35a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("brand_alias_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brands", "brand_alias_name")
