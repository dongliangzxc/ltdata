"""brands: add original_brand_name column

Revision ID: p32a1b2c3d4e5
Revises: p31a1b2c3d4e5
Create Date: 2026-07-07

将品牌管理里的「上传时品牌名称」以 original_brand_name 落库；一次写入不再修改，
存量数据用当前 brand_name 回填，视为该品牌创建时的原始名。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p32a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p31a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("original_brand_name", sa.String(length=200), nullable=True),
    )
    # 回填存量：把当前 brand_name 视作该品牌的原始上传名
    op.execute(
        "UPDATE brands SET original_brand_name = brand_name "
        "WHERE original_brand_name IS NULL"
    )


def downgrade() -> None:
    op.drop_column("brands", "original_brand_name")
